"""
Core memory engine for Sigil.
4 memory types: semantic, episodic, procedural, working.
Hybrid retrieval: vector similarity + FTS5 + importance + recency + graph boost.
"""

import json
import math
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sigil.memory.schema import SCHEMA_SQL, SCHEMA_SQL_EXTRA, SCHEMA_VERSION, migrate
from sigil.memory.embeddings import embed, cosine_similarity, has_embeddings, text_hash


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _uid() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class MemoryResult:
    id: str
    content: str
    table: str
    score: float
    importance: float = 0.5
    created_at: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class MemoryEngine:
    """
    The core memory engine. One SQLite file, four memory types,
    hybrid retrieval, automatic FTS5 indexing.
    """

    def __init__(self, db_path: str = "~/.sigil/brain.db", agent_id: str = "default",
                 wm_ttl_hours: int = 24, wm_max_items: int = 10000,
                 recency_halflife_hours: float = 168.0):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.agent_id = agent_id
        self.wm_ttl_hours = wm_ttl_hours
        self.wm_max_items = wm_max_items
        self.recency_halflife = recency_halflife_hours
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            self._conn.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
            self._conn.execute("PRAGMA temp_store=MEMORY")
        return self._conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        conn.executescript(SCHEMA_SQL_EXTRA)

        # Check for schema migrations on existing databases
        try:
            row = conn.execute(
                "SELECT value FROM sigil_meta WHERE key = 'schema_version'"
            ).fetchone()
            current = int(row["value"]) if row else 0
        except (sqlite3.OperationalError, TypeError):
            current = 0

        if current < SCHEMA_VERSION:
            migrate(conn, current)

        conn.execute(
            "INSERT OR REPLACE INTO sigil_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION))
        )
        conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Semantic Memory ──────────────────────────────────────────────

    def remember_semantic(self, content: str, category: str = "general",
                          importance: float = 0.5, source: str = "user",
                          metadata: Optional[dict] = None) -> str:
        """Store a semantic fact."""
        conn = self._get_conn()
        mid = f"sem_{_uid()}"
        now = _now()
        meta = json.dumps(metadata or {})

        conn.execute(
            """INSERT INTO semantic (id, content, category, importance, source,
               agent_id, created_at, updated_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mid, content, category, importance, source, self.agent_id, now, now, meta)
        )

        # Embed and store vector
        vec = embed(content)
        if vec:
            conn.execute(
                """INSERT INTO vectors (id, memory_id, memory_table, embedding, dimensions, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (f"vec_{_uid()}", mid, "semantic", vec, len(vec) // 4, now)
            )

        conn.commit()
        return mid

    def remember_episodic(self, summary: str, detail: str = "",
                          outcome: str = "", importance: float = 0.5,
                          source: str = "conversation", session_id: str = "",
                          tags: Optional[list] = None,
                          metadata: Optional[dict] = None) -> str:
        """Store an episodic event."""
        conn = self._get_conn()
        mid = f"epi_{_uid()}"
        now = _now()
        tags_json = json.dumps(tags or [])
        meta = json.dumps(metadata or {})

        conn.execute(
            """INSERT INTO episodic (id, summary, detail, outcome, importance,
               source, agent_id, session_id, created_at, tags, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mid, summary, detail, outcome, importance, source,
             self.agent_id, session_id, now, tags_json, meta)
        )

        vec = embed(summary + " " + detail)
        if vec:
            conn.execute(
                """INSERT INTO vectors (id, memory_id, memory_table, embedding, dimensions, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (f"vec_{_uid()}", mid, "episodic", vec, len(vec) // 4, now)
            )

        conn.commit()
        return mid

    def remember_procedural(self, name: str, steps: list[str],
                            metadata: Optional[dict] = None) -> str:
        """Store a procedural workflow."""
        conn = self._get_conn()
        mid = f"proc_{_uid()}"
        now = _now()
        steps_json = json.dumps(steps)
        meta = json.dumps(metadata or {})

        conn.execute(
            """INSERT INTO procedural (id, name, steps, agent_id, created_at,
               updated_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (mid, name, steps_json, self.agent_id, now, now, meta)
        )

        vec = embed(name + " " + " ".join(steps))
        if vec:
            conn.execute(
                """INSERT INTO vectors (id, memory_id, memory_table, embedding, dimensions, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (f"vec_{_uid()}", mid, "procedural", vec, len(vec) // 4, now)
            )

        conn.commit()
        return mid

    def evolve_procedure(self, proc_id: str, failed_at_step: int,
                         failure_context: str, new_steps: Optional[list[str]] = None) -> bool:
        """Evolve a procedural memory after failure (Mengram-inspired)."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM procedural WHERE id = ?", (proc_id,)).fetchone()
        if not row:
            return False

        now = _now()
        steps = json.loads(row["steps"])
        version = row["version"] + 1

        if new_steps:
            steps = new_steps
        else:
            # Insert a checkpoint step after the failed step
            if 0 <= failed_at_step < len(steps):
                steps.insert(failed_at_step + 1,
                             f"[AUTO-FIX v{version}] Verify: {failure_context}")

        conn.execute(
            """UPDATE procedural SET steps = ?, version = ?, failure_count = failure_count + 1,
               last_outcome = 'failed', last_failure_context = ?, updated_at = ?
               WHERE id = ?""",
            (json.dumps(steps), version, failure_context, now, proc_id)
        )

        # Re-embed
        vec = embed(row["name"] + " " + " ".join(steps))
        if vec:
            conn.execute("DELETE FROM vectors WHERE memory_id = ? AND memory_table = 'procedural'",
                         (proc_id,))
            conn.execute(
                """INSERT INTO vectors (id, memory_id, memory_table, embedding, dimensions, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (f"vec_{_uid()}", proc_id, "procedural", vec, len(vec) // 4, now)
            )

        conn.commit()
        return True

    def remember_working(self, content: str, importance: float = 0.5,
                         session_id: str = "", ttl_hours: Optional[int] = None) -> str:
        """Store working memory (hot context, auto-expires)."""
        conn = self._get_conn()
        mid = f"wm_{_uid()}"
        now = _now()
        ttl = ttl_hours or self.wm_ttl_hours
        expires = (datetime.now(timezone.utc) + timedelta(hours=ttl)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f")

        conn.execute(
            """INSERT INTO working (id, content, importance, session_id, agent_id,
               created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (mid, content, importance, session_id, self.agent_id, now, expires)
        )

        # Embed for vector search (working memory is now searchable)
        vec = embed(content)
        if vec:
            conn.execute(
                """INSERT INTO vectors (id, memory_id, memory_table, embedding, dimensions, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (f"vec_{_uid()}", mid, "working", vec, len(vec) // 4, now)
            )

        conn.commit()

        # Enforce max items
        count = conn.execute("SELECT COUNT(*) FROM working WHERE agent_id = ?",
                             (self.agent_id,)).fetchone()[0]
        if count > self.wm_max_items:
            conn.execute(
                """DELETE FROM working WHERE id IN (
                   SELECT id FROM working WHERE agent_id = ?
                   ORDER BY importance ASC, created_at ASC
                   LIMIT ?)""",
                (self.agent_id, count - self.wm_max_items)
            )
            conn.commit()

        return mid

    # ── Unified Remember ─────────────────────────────────────────────

    def remember(self, content: str, type: str = "semantic", **kwargs) -> str:
        """
        Unified remember interface.
        type: 'semantic', 'episodic', 'procedural', 'working'
        """
        if type == "semantic":
            return self.remember_semantic(content, **kwargs)
        elif type == "episodic":
            # Use content as summary if summary not provided
            if "summary" not in kwargs:
                kwargs["summary"] = content
            return self.remember_episodic(**kwargs)
        elif type == "procedural":
            name = kwargs.pop("name", content[:50])
            steps = kwargs.pop("steps", [content])
            return self.remember_procedural(name, steps, **kwargs)
        elif type == "working":
            return self.remember_working(content, **kwargs)
        else:
            raise ValueError(f"Unknown memory type: {type}")

    # ── Recall / Retrieval ───────────────────────────────────────────

    def recall(self, query: str, top_k: int = 5,
               tables: Optional[list[str]] = None,
               min_importance: float = 0.0,
               include_expired_working: bool = False) -> list[MemoryResult]:
        """
        Hybrid recall: 50% vector + 30% FTS5 + 20% (importance + recency + graph boost).
        Searches across all memory tables by default.
        """
        target_tables = tables or ["semantic", "episodic", "procedural", "working"]
        candidates: list[MemoryResult] = []

        # Clean expired working memory
        if not include_expired_working:
            self._evict_working()

        # Vector search
        query_vec = embed(query)
        vec_scores: dict[str, float] = {}
        if query_vec:
            vec_scores = self._vector_search(query_vec, target_tables, top_k * 3)

        # FTS5 search
        fts_scores = self._fts_search(query, target_tables, top_k * 3)

        # Merge candidates
        all_ids = set(vec_scores.keys()) | set(fts_scores.keys())

        conn = self._get_conn()
        now = datetime.now(timezone.utc)

        for mem_key in all_ids:
            table, mid = mem_key.split(":", 1)
            row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (mid,)).fetchone()
            if not row:
                continue

            # Get content based on table
            if table == "semantic":
                content = row["content"]
                importance = row["importance"]
            elif table == "episodic":
                content = row["summary"]
                if row["detail"]:
                    content += f" | {row['detail']}"
                if row["outcome"]:
                    content += f" [outcome: {row['outcome']}]"
                importance = row["importance"]
            elif table == "procedural":
                content = f"{row['name']}: {row['steps']}"
                importance = 0.5 + (row["success_count"] / max(1, row["success_count"] + row["failure_count"])) * 0.5
            elif table == "working":
                content = row["content"]
                importance = row["importance"]
            else:
                continue

            if importance < min_importance:
                continue

            # Compute hybrid score
            v_score = vec_scores.get(mem_key, 0.0)
            f_score = fts_scores.get(mem_key, 0.0)

            # Recency decay (exponential, configurable halflife)
            created = datetime.fromisoformat(row["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            hours_ago = max(0, (now - created).total_seconds() / 3600)
            recency = math.exp(-0.693 * hours_ago / self.recency_halflife)

            # Composite score: 50% vector + 30% FTS + 10% importance + 10% recency
            score = (0.50 * v_score) + (0.30 * f_score) + (0.10 * importance) + (0.10 * recency)

            meta = json.loads(row["metadata"]) if "metadata" in row.keys() else {}
            candidates.append(MemoryResult(
                id=mid,
                content=content,
                table=table,
                score=score,
                importance=importance,
                created_at=row["created_at"],
                metadata=meta
            ))

        # Sort by score, return top_k
        candidates.sort(key=lambda x: x.score, reverse=True)

        # Bump access count for semantic hits
        for result in candidates[:top_k]:
            if result.table == "semantic":
                conn.execute(
                    "UPDATE semantic SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                    (_now(), result.id)
                )
        conn.commit()

        return candidates[:top_k]

    def _vector_search(self, query_vec: bytes, tables: list[str],
                       limit: int) -> dict[str, float]:
        """Search vectors by cosine similarity with dimension validation."""
        conn = self._get_conn()
        scores: dict[str, float] = {}
        query_dims = len(query_vec) // 4

        rows = conn.execute(
            """SELECT memory_id, memory_table, embedding FROM vectors
               WHERE memory_table IN ({})
               LIMIT ?""".format(",".join("?" * len(tables))),
            (*tables, limit * 10)
        ).fetchall()

        for row in rows:
            # Skip vectors with mismatched dimensions (model change safety)
            if len(row["embedding"]) != len(query_vec):
                continue
            sim = cosine_similarity(query_vec, row["embedding"])
            key = f"{row['memory_table']}:{row['memory_id']}"
            scores[key] = max(0, sim)  # Clamp negatives

        # Normalize to [0, 1]
        if scores:
            max_s = max(scores.values()) or 1.0
            scores = {k: v / max_s for k, v in scores.items()}

        # Keep only top results
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        return dict(sorted_scores)

    def _fts_search(self, query: str, tables: list[str], limit: int) -> dict[str, float]:
        """Search via FTS5 across memory tables."""
        conn = self._get_conn()
        scores: dict[str, float] = {}

        # Escape FTS5 special characters
        safe_query = query.replace('"', '""')
        # Use prefix matching for better recall
        terms = safe_query.split()
        fts_query = " OR ".join(f'"{t}"*' for t in terms if t.strip())
        if not fts_query:
            return scores

        fts_tables = {
            "semantic": ("semantic_fts", "semantic"),
            "episodic": ("episodic_fts", "episodic"),
            "procedural": ("procedural_fts", "procedural"),
            "working": ("working_fts", "working"),
        }

        for table in tables:
            if table not in fts_tables:
                continue
            fts_name, real_table = fts_tables[table]
            try:
                rows = conn.execute(
                    f"""SELECT {real_table}.id, rank
                        FROM {fts_name}
                        JOIN {real_table} ON {real_table}.rowid = {fts_name}.rowid
                        WHERE {fts_name} MATCH ?
                        ORDER BY rank
                        LIMIT ?""",
                    (fts_query, limit)
                ).fetchall()
                for row in rows:
                    key = f"{table}:{row['id']}"
                    # FTS5 rank is negative (lower = better), normalize
                    scores[key] = 1.0 / (1.0 + abs(row["rank"]))
            except sqlite3.OperationalError:
                continue

        # Normalize
        if scores:
            max_s = max(scores.values()) or 1.0
            scores = {k: v / max_s for k, v in scores.items()}

        return scores

    def _evict_working(self):
        """Remove expired working memory and their vectors."""
        conn = self._get_conn()
        now = _now()
        # Clean up vectors for expired working memories
        conn.execute(
            """DELETE FROM vectors WHERE memory_table = 'working'
               AND memory_id IN (SELECT id FROM working WHERE expires_at < ?)""",
            (now,)
        )
        conn.execute("DELETE FROM working WHERE expires_at < ?", (now,))
        conn.commit()

    # ── Utility Methods ──────────────────────────────────────────────

    def get(self, memory_id: str) -> Optional[dict]:
        """Get a specific memory by ID."""
        conn = self._get_conn()
        prefix = memory_id.split("_")[0]
        table_map = {"sem": "semantic", "epi": "episodic", "proc": "procedural", "wm": "working"}
        table = table_map.get(prefix)
        if not table:
            return None
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def delete(self, memory_id: str) -> bool:
        """Delete a memory and its vector."""
        conn = self._get_conn()
        prefix = memory_id.split("_")[0]
        table_map = {"sem": "semantic", "epi": "episodic", "proc": "procedural", "wm": "working"}
        table = table_map.get(prefix)
        if not table:
            return False
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (memory_id,))
        conn.execute("DELETE FROM vectors WHERE memory_id = ?", (memory_id,))
        conn.commit()
        return True

    # Tables that have an agent_id column
    _AGENT_SCOPED_TABLES = {"semantic", "episodic", "procedural", "working"}

    def count(self, table: Optional[str] = None) -> dict[str, int]:
        """Count memories by table (scoped to current agent)."""
        conn = self._get_conn()
        valid_tables = {"semantic", "episodic", "procedural", "working"}
        tables = [table] if table and table in valid_tables else sorted(valid_tables)
        result = {}
        for t in tables:
            row = conn.execute(
                f"SELECT COUNT(*) as c FROM {t} WHERE agent_id = ?",
                (self.agent_id,)
            ).fetchone()
            result[t] = row["c"]
        return result

    def stats(self) -> dict:
        """Full database statistics (scoped to current agent)."""
        counts = self.count()
        conn = self._get_conn()
        vec_count = conn.execute(
            """SELECT COUNT(*) as c FROM vectors
               WHERE memory_table IN ('semantic','episodic','procedural','working')
               AND memory_id IN (
                   SELECT id FROM semantic WHERE agent_id = ?
                   UNION SELECT id FROM episodic WHERE agent_id = ?
                   UNION SELECT id FROM procedural WHERE agent_id = ?
                   UNION SELECT id FROM working WHERE agent_id = ?
               )""",
            (self.agent_id, self.agent_id, self.agent_id, self.agent_id)
        ).fetchone()["c"]
        triple_count = conn.execute(
            "SELECT COUNT(*) as c FROM triples WHERE agent_id = ?",
            (self.agent_id,)
        ).fetchone()["c"]
        event_count = conn.execute(
            "SELECT COUNT(*) as c FROM events WHERE agent_id = ?",
            (self.agent_id,)
        ).fetchone()["c"]
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "memories": counts,
            "vectors": vec_count,
            "triples": triple_count,
            "events": event_count,
            "db_size_bytes": db_size,
            "db_size_mb": round(db_size / 1024 / 1024, 2),
            "has_embeddings": has_embeddings(),
            "agent_id": self.agent_id,
        }

    def export_json(self, path: str):
        """Export this agent's memory to JSON for migration."""
        conn = self._get_conn()
        data = {"version": SCHEMA_VERSION, "agent_id": self.agent_id, "exported_at": _now()}
        # Agent-scoped tables
        for table in ["semantic", "episodic", "procedural", "working", "triples", "events"]:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE agent_id = ?",
                (self.agent_id,)
            ).fetchall()
            data[table] = [dict(r) for r in rows]
        # Projects/tasks are shared (no agent_id column) — export all
        for table in ["projects", "tasks"]:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            data[table] = [dict(r) for r in rows]
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    # Allowed columns per table for safe import (whitelist)
    _IMPORT_COLUMNS = {
        "semantic": {"id", "content", "category", "importance", "source", "agent_id",
                     "created_at", "updated_at", "access_count", "last_accessed",
                     "decay_class", "metadata"},
        "episodic": {"id", "summary", "detail", "outcome", "emotion", "importance",
                     "source", "agent_id", "session_id", "created_at", "tags", "metadata"},
        "procedural": {"id", "name", "steps", "version", "success_count", "failure_count",
                       "last_outcome", "last_failure_context", "agent_id", "created_at",
                       "updated_at", "metadata"},
        "working": {"id", "content", "importance", "session_id", "agent_id",
                    "created_at", "expires_at", "metadata"},
        "triples": {"id", "subject", "predicate", "object", "confidence", "source",
                    "agent_id", "valid_from", "valid_until", "created_at", "metadata"},
        "events": {"id", "agent_id", "event_type", "payload", "memory_id",
                   "memory_table", "created_at", "synced_by"},
    }

    def import_json(self, path: str):
        """Import memory from JSON export."""
        with open(path) as f:
            data = json.load(f)
        conn = self._get_conn()
        for table in ["semantic", "episodic", "procedural", "working", "triples", "events"]:
            if table not in data:
                continue
            allowed = self._IMPORT_COLUMNS.get(table, set())
            for row in data[table]:
                # Whitelist columns to prevent SQL injection via key names
                safe_row = {k: v for k, v in row.items() if k in allowed}
                if not safe_row or "id" not in safe_row:
                    continue
                cols = ", ".join(safe_row.keys())
                placeholders = ", ".join("?" * len(safe_row))
                try:
                    conn.execute(
                        f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})",
                        list(safe_row.values())
                    )
                except sqlite3.Error:
                    continue
        conn.commit()
