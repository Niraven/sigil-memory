"""
Entity Linking for Sigil.
Inspired by Mem0's v3 multi-signal retrieval with entity matching.

Extracts entities from memory content and cross-links them in the
knowledge graph for boosted retrieval.
"""

import re
import json
import hashlib
import sqlite3
from typing import Optional


# Lightweight NER patterns (no spaCy dependency)
ENTITY_PATTERNS = [
    # Capitalized words (likely proper nouns)
    (r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', "name"),
    # URLs
    (r'(https?://[^\s]+)', "url"),
    # Email
    (r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', "email"),
    # @handles
    (r'(@\w+)', "handle"),
    # File paths
    (r'(/[\w./\-]+\.\w+)', "file"),
    # Tech terms (common in AI/dev context)
    (r'\b(Python|TypeScript|JavaScript|React|PostgreSQL|SQLite|Redis|Docker|Kubernetes|GitHub|Discord|Telegram|Slack|OAuth|JWT|GraphQL|REST|API|LLM|RAG|GPU|CPU|SSD|NFS)\b', "tech"),
]

# Common words to exclude from entity extraction
STOP_ENTITIES = {
    "the", "and", "for", "with", "this", "that", "from", "have", "been",
    "will", "can", "not", "but", "are", "was", "were", "has", "had",
    "would", "could", "should", "may", "might", "must", "shall",
    "also", "just", "then", "than", "when", "what", "where", "which",
    "who", "how", "why", "all", "each", "every", "both", "few",
    "more", "most", "some", "such", "only", "very", "still",
    "Here", "There", "Now", "Then", "After", "Before", "During",
}


class EntityLinker:
    """
    Extracts entities from text and links them in the knowledge graph.
    """

    def __init__(self, conn: sqlite3.Connection, agent_id: str = "default"):
        self.conn = conn
        self.agent_id = agent_id

    def extract_entities(self, text: str) -> list[dict]:
        """Extract entities from text using pattern matching."""
        entities = []
        seen = set()

        for pattern, entity_type in ENTITY_PATTERNS:
            for match in re.finditer(pattern, text):
                value = match.group(1).strip()
                # Skip short or stop words
                if len(value) < 2 or value in STOP_ENTITIES:
                    continue
                key = (value.lower(), entity_type)
                if key not in seen:
                    seen.add(key)
                    entities.append({
                        "value": value,
                        "type": entity_type,
                        "position": match.start(),
                    })

        return entities

    @staticmethod
    def _deterministic_id(subject: str, predicate: str, obj: str, agent_id: str) -> str:
        """Generate a deterministic triple ID from (S, P, O, agent) to prevent duplicates."""
        key = f"{subject}|{predicate}|{obj}|{agent_id}"
        return f"elink_{hashlib.sha256(key.encode()).hexdigest()[:12]}"

    def link_memory(self, memory_id: str, memory_table: str,
                    content: str) -> int:
        """
        Extract entities from memory content and create graph links.
        Uses deterministic IDs so repeated calls don't create duplicates.
        Returns number of links created.
        """
        entities = self.extract_entities(content)
        links_created = 0
        now = self.conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%f', 'now')").fetchone()[0]

        for entity in entities:
            # Deterministic ID: same memory+entity always produces same triple
            tid = self._deterministic_id(
                memory_id, "mentions", entity["value"].lower(), self.agent_id)

            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO triples
                       (id, subject, predicate, object, confidence, source,
                        agent_id, valid_from, created_at, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (tid, memory_id, "mentions", entity["value"].lower(),
                     0.8, "entity_linking", self.agent_id, now, now,
                     json.dumps({"entity_type": entity["type"],
                                 "memory_table": memory_table}))
                )
                links_created += 1
            except sqlite3.IntegrityError:
                continue  # Already exists — dedup working
            except sqlite3.Error:
                continue

        # Create entity-to-entity co-occurrence links (deduplicated)
        if len(entities) >= 2:
            for i, e1 in enumerate(entities):
                for e2 in entities[i + 1:]:
                    # Deterministic: sorted pair ensures (A,B) == (B,A)
                    pair = sorted([e1["value"].lower(), e2["value"].lower()])
                    tid = self._deterministic_id(
                        pair[0], "co_occurs_with", pair[1], self.agent_id)
                    try:
                        # Use UPSERT to bump confidence on re-encounter
                        existing = self.conn.execute(
                            "SELECT confidence FROM triples WHERE id = ?", (tid,)
                        ).fetchone()
                        if existing:
                            new_conf = min(1.0, existing["confidence"] + 0.05)
                            self.conn.execute(
                                "UPDATE triples SET confidence = ? WHERE id = ?",
                                (new_conf, tid))
                        else:
                            self.conn.execute(
                                """INSERT INTO triples
                                   (id, subject, predicate, object, confidence,
                                    source, agent_id, valid_from, created_at, metadata)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (tid, pair[0], "co_occurs_with", pair[1],
                                 0.6, "entity_linking", self.agent_id, now, now,
                                 json.dumps({"context": memory_id}))
                            )
                    except sqlite3.Error:
                        continue

        if links_created > 0 or len(entities) >= 2:
            self.conn.commit()

        return links_created

    def entity_boost(self, query: str, memory_content: str) -> float:
        """
        Calculate entity-based retrieval boost.
        If query and memory share linked entities, boost the score.
        """
        query_entities = {e["value"].lower() for e in self.extract_entities(query)}
        memory_entities = {e["value"].lower() for e in self.extract_entities(memory_content)}

        if not query_entities or not memory_entities:
            return 0.0

        # Direct overlap
        overlap = query_entities & memory_entities
        if overlap:
            return min(len(overlap) * 0.1, 0.3)

        # Graph-connected entities (1-hop)
        for qe in query_entities:
            connected = self.conn.execute(
                """SELECT object FROM triples
                   WHERE subject = ? AND predicate = 'co_occurs_with'
                   AND agent_id = ? AND valid_until IS NULL
                   LIMIT 10""",
                (qe, self.agent_id)
            ).fetchall()
            connected_set = {r["object"] for r in connected}
            indirect_overlap = connected_set & memory_entities
            if indirect_overlap:
                return min(len(indirect_overlap) * 0.05, 0.15)

        return 0.0

    def stats(self) -> dict:
        """Entity linking statistics."""
        mention_count = self.conn.execute(
            """SELECT COUNT(*) as c FROM triples
               WHERE source = 'entity_linking' AND agent_id = ?
               AND predicate = 'mentions'""",
            (self.agent_id,)
        ).fetchone()["c"]

        cooccur_count = self.conn.execute(
            """SELECT COUNT(*) as c FROM triples
               WHERE source = 'entity_linking' AND agent_id = ?
               AND predicate = 'co_occurs_with'""",
            (self.agent_id,)
        ).fetchone()["c"]

        unique_entities = self.conn.execute(
            """SELECT COUNT(DISTINCT object) as c FROM triples
               WHERE source = 'entity_linking' AND agent_id = ?
               AND predicate = 'mentions'""",
            (self.agent_id,)
        ).fetchone()["c"]

        return {
            "mention_links": mention_count,
            "co_occurrence_links": cooccur_count,
            "unique_entities": unique_entities,
        }
