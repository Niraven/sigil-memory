"""
Temporal Knowledge Graph for Sigil.
Stores (subject, predicate, object) triples with time validity windows.
Auto-invalidates stale facts. Boost scoring for retrieval.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _uid() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Triple:
    id: str
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0
    source: str = "extraction"
    agent_id: str = "default"
    valid_from: str = ""
    valid_until: Optional[str] = None
    created_at: str = ""
    metadata: dict = field(default_factory=dict)

    def is_valid(self, as_of: Optional[str] = None) -> bool:
        check_time = as_of or _now()
        if self.valid_from and check_time < self.valid_from:
            return False
        if self.valid_until and check_time > self.valid_until:
            return False
        return True

    def to_dict(self):
        return asdict(self)


@dataclass
class Entity:
    name: str
    triples: list[Triple] = field(default_factory=list)
    in_degree: int = 0
    out_degree: int = 0

    @property
    def degree(self):
        return self.in_degree + self.out_degree

    def facts(self, as_of: Optional[str] = None) -> list[Triple]:
        return [t for t in self.triples if t.is_valid(as_of)]


class KnowledgeGraph:
    """
    Temporal knowledge graph built on top of Sigil's SQLite store.
    """

    def __init__(self, conn: sqlite3.Connection, agent_id: str = "default"):
        self.conn = conn
        self.agent_id = agent_id

    def add(self, subject: str, predicate: str, obj: str,
            confidence: float = 1.0, source: str = "extraction",
            valid_from: Optional[str] = None,
            valid_until: Optional[str] = None,
            metadata: Optional[dict] = None) -> str:
        """Add a triple to the knowledge graph."""
        tid = f"triple_{_uid()}"
        now = _now()
        meta = json.dumps(metadata or {})

        # Check for existing contradictory triples and invalidate them
        self._invalidate_contradictions(subject, predicate, obj, now)

        self.conn.execute(
            """INSERT INTO triples (id, subject, predicate, object, confidence,
               source, agent_id, valid_from, valid_until, created_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tid, subject.lower(), predicate.lower(), obj,
             confidence, source, self.agent_id,
             valid_from or now, valid_until, now, meta)
        )
        self.conn.commit()
        return tid

    def _invalidate_contradictions(self, subject: str, predicate: str,
                                   new_obj: str, now: str):
        """
        When a new triple (S, P, O') is added for a predicate that implies
        uniqueness (e.g., 'works_at', 'lives_in', 'role_is'), invalidate
        previous triples (S, P, O) where O != O'.
        """
        unique_predicates = {
            "works_at", "lives_in", "role_is", "assigned_to", "status_is",
            "email_is", "phone_is", "title_is", "reports_to", "located_in",
            "uses_model", "preferred_language", "timezone_is"
        }
        if predicate.lower() not in unique_predicates:
            return

        self.conn.execute(
            """UPDATE triples SET valid_until = ?
               WHERE subject = ? AND predicate = ? AND object != ?
               AND valid_until IS NULL AND agent_id = ?""",
            (now, subject.lower(), predicate.lower(), new_obj, self.agent_id)
        )

    def query(self, subject: Optional[str] = None,
              predicate: Optional[str] = None,
              obj: Optional[str] = None,
              as_of: Optional[str] = None,
              include_expired: bool = False,
              limit: int = 100) -> list[Triple]:
        """Query the knowledge graph with optional time-awareness."""
        conditions = ["agent_id = ?"]
        params: list = [self.agent_id]

        if subject:
            conditions.append("subject = ?")
            params.append(subject.lower())
        if predicate:
            conditions.append("predicate = ?")
            params.append(predicate.lower())
        if obj:
            conditions.append("object = ?")
            params.append(obj)

        if not include_expired:
            check_time = as_of or _now()
            conditions.append("valid_from <= ?")
            params.append(check_time)
            conditions.append("(valid_until IS NULL OR valid_until > ?)")
            params.append(check_time)

        where = " AND ".join(conditions)
        rows = self.conn.execute(
            f"SELECT * FROM triples WHERE {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit)
        ).fetchall()

        return [Triple(
            id=r["id"], subject=r["subject"], predicate=r["predicate"],
            object=r["object"], confidence=r["confidence"], source=r["source"],
            agent_id=r["agent_id"], valid_from=r["valid_from"],
            valid_until=r["valid_until"], created_at=r["created_at"],
            metadata=json.loads(r["metadata"])
        ) for r in rows]

    def search(self, query: str, limit: int = 20,
               as_of: Optional[str] = None) -> list[Triple]:
        """FTS5 search across triples."""
        terms = query.split()
        fts_query = " OR ".join(f'"{t}"*' for t in terms if t.strip())
        if not fts_query:
            return []

        try:
            rows = self.conn.execute(
                """SELECT triples.* FROM triples_fts
                   JOIN triples ON triples.rowid = triples_fts.rowid
                   WHERE triples_fts MATCH ? AND triples.agent_id = ?
                   ORDER BY rank LIMIT ?""",
                (fts_query, self.agent_id, limit)
            ).fetchall()

            triples = [Triple(
                id=r["id"], subject=r["subject"], predicate=r["predicate"],
                object=r["object"], confidence=r["confidence"], source=r["source"],
                agent_id=r["agent_id"], valid_from=r["valid_from"],
                valid_until=r["valid_until"], created_at=r["created_at"],
                metadata=json.loads(r["metadata"])
            ) for r in rows]

            if as_of:
                triples = [t for t in triples if t.is_valid(as_of)]

            return triples
        except sqlite3.OperationalError:
            return []

    def entity(self, name: str, as_of: Optional[str] = None) -> Entity:
        """Get full entity profile with all its triples."""
        outgoing = self.query(subject=name, as_of=as_of, limit=500)
        incoming = self.query(obj=name, as_of=as_of, limit=500)
        all_triples = outgoing + incoming
        # Deduplicate
        seen = set()
        unique = []
        for t in all_triples:
            if t.id not in seen:
                seen.add(t.id)
                unique.append(t)

        return Entity(
            name=name,
            triples=unique,
            out_degree=len(outgoing),
            in_degree=len(incoming)
        )

    def neighbors(self, name: str, depth: int = 1,
                  as_of: Optional[str] = None) -> list[Entity]:
        """Get entities connected to the given entity, up to N hops."""
        visited = set()
        result = []
        queue = [(name.lower(), 0)]

        while queue:
            current, d = queue.pop(0)
            if current in visited or d > depth:
                continue
            visited.add(current)

            ent = self.entity(current, as_of)
            if d > 0:  # Don't include the starting entity
                result.append(ent)

            if d < depth:
                for t in ent.triples:
                    next_name = t.object if t.subject == current else t.subject
                    if next_name not in visited:
                        queue.append((next_name, d + 1))

        return result

    def boost_score(self, memory_content: str, query: str) -> float:
        """
        Graph boost: if the query and memory share entities in the graph,
        boost the memory's retrieval score.
        """
        query_terms = set(query.lower().split())
        content_terms = set(memory_content.lower().split())
        all_terms = query_terms | content_terms

        boost = 0.0
        for term in all_terms:
            # Check if term is a known entity
            triples = self.query(subject=term, limit=1)
            if triples:
                # Entity in query AND content = strong signal
                if term in query_terms and term in content_terms:
                    boost += 0.15
                else:
                    boost += 0.05

        return min(boost, 0.5)  # Cap at 0.5

    def invalidate(self, triple_id: str) -> bool:
        """Manually invalidate a triple."""
        now = _now()
        result = self.conn.execute(
            "UPDATE triples SET valid_until = ? WHERE id = ? AND valid_until IS NULL",
            (now, triple_id)
        )
        self.conn.commit()
        return result.rowcount > 0

    def stats(self) -> dict:
        """Knowledge graph statistics."""
        total = self.conn.execute(
            "SELECT COUNT(*) as c FROM triples WHERE agent_id = ?",
            (self.agent_id,)
        ).fetchone()["c"]
        active = self.conn.execute(
            """SELECT COUNT(*) as c FROM triples
               WHERE agent_id = ? AND valid_until IS NULL""",
            (self.agent_id,)
        ).fetchone()["c"]
        expired = total - active

        subjects = self.conn.execute(
            """SELECT COUNT(DISTINCT subject) as c FROM triples
               WHERE agent_id = ? AND valid_until IS NULL""",
            (self.agent_id,)
        ).fetchone()["c"]
        predicates = self.conn.execute(
            """SELECT COUNT(DISTINCT predicate) as c FROM triples
               WHERE agent_id = ? AND valid_until IS NULL""",
            (self.agent_id,)
        ).fetchone()["c"]

        return {
            "total_triples": total,
            "active_triples": active,
            "expired_triples": expired,
            "unique_entities": subjects,
            "unique_predicates": predicates,
        }
