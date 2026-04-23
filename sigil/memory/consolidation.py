"""
Sleep Consolidation + Reflection for Sigil.
Inspired by Mnemosyne's sleep consolidation + MemGPT's virtual context management.

Three consolidation patterns:
1. Sleep: compress old working memory into episodic summaries
2. Reflection: periodic self-review of memory for contradictions and gaps
3. Surprise detection: flag memories that contradict existing knowledge
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from sigil.memory.embeddings import embed, cosine_similarity


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


class MemoryConsolidator:
    """
    Handles memory lifecycle: consolidation, reflection, surprise detection.
    """

    def __init__(self, conn: sqlite3.Connection, agent_id: str = "default"):
        self.conn = conn
        self.agent_id = agent_id

    def sleep(self, max_age_hours: int = 24, batch_size: int = 50) -> dict:
        """
        Sleep consolidation: compress old working memory into episodic summaries.
        Groups related working memories and creates condensed episodic entries.
        Returns stats about what was consolidated.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f")

        # Get old working memory entries
        rows = self.conn.execute(
            """SELECT id, content, importance, session_id, created_at
               FROM working WHERE agent_id = ? AND created_at < ?
               ORDER BY created_at ASC LIMIT ?""",
            (self.agent_id, cutoff, batch_size)
        ).fetchall()

        if not rows:
            return {"consolidated": 0, "removed": 0}

        # Group by session
        sessions: dict[str, list] = {}
        for r in rows:
            sid = r["session_id"] or "no_session"
            if sid not in sessions:
                sessions[sid] = []
            sessions[sid].append(dict(r))

        consolidated = 0
        removed_ids = []

        for session_id, memories in sessions.items():
            if len(memories) == 0:
                continue

            # Create condensed summary
            contents = [m["content"] for m in memories]
            max_importance = max(m["importance"] for m in memories)
            summary = self._condense(contents)

            # Store as episodic memory
            from sigil.memory.engine import _uid
            mid = f"epi_{_uid()}"
            now = _now()

            self.conn.execute(
                """INSERT INTO episodic (id, summary, detail, outcome, importance,
                   source, agent_id, session_id, created_at, tags, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mid, summary, json.dumps(contents), "consolidated",
                 max_importance, "consolidation", self.agent_id,
                 session_id if session_id != "no_session" else "",
                 now, json.dumps(["consolidated", "sleep"]),
                 json.dumps({"source_count": len(memories)}))
            )

            # Embed the summary
            vec = embed(summary)
            if vec:
                self.conn.execute(
                    """INSERT INTO vectors (id, memory_id, memory_table, embedding,
                       dimensions, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (f"vec_{_uid()}", mid, "episodic", vec, len(vec) // 4, now)
                )

            removed_ids.extend(m["id"] for m in memories)
            consolidated += 1

        # Remove consolidated working memories
        if removed_ids:
            placeholders = ",".join("?" * len(removed_ids))
            self.conn.execute(
                f"DELETE FROM working WHERE id IN ({placeholders})", removed_ids)

        self.conn.commit()

        return {
            "consolidated": consolidated,
            "removed": len(removed_ids),
            "sessions_processed": len(sessions),
        }

    def _condense(self, contents: list[str]) -> str:
        """Condense multiple memory contents into a summary."""
        if len(contents) == 1:
            return contents[0]

        # Simple extractive summary: take the first sentence of each,
        # deduplicate, and join. For production, this would use an LLM.
        seen = set()
        parts = []
        for c in contents:
            # Take first meaningful chunk
            chunk = c.strip()[:150]
            normalized = chunk.lower()
            if normalized not in seen:
                seen.add(normalized)
                parts.append(chunk)

        return "; ".join(parts[:10])

    def detect_contradictions(self, limit: int = 50) -> list[dict]:
        """
        Scan recent semantic memories for contradictions with the knowledge graph.
        Uses indexed lookups instead of O(n*m) full scan.
        Returns list of potential contradictions for review.
        """
        contradictions = []

        # Pre-load active triples once (indexed by subject for fast lookup)
        triples = self.conn.execute(
            """SELECT subject, predicate, object FROM triples
               WHERE agent_id = ? AND valid_until IS NULL""",
            (self.agent_id,)
        ).fetchall()

        # Build subject -> triples index
        subject_index: dict[str, list] = {}
        for t in triples:
            subj = t["subject"]
            if subj not in subject_index:
                subject_index[subj] = []
            subject_index[subj].append(t)

        # Get recent semantic memories
        rows = self.conn.execute(
            """SELECT id, content, created_at FROM semantic
               WHERE agent_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (self.agent_id, limit)
        ).fetchall()

        for row in rows:
            content_lower = row["content"].lower()

            # Only check triples whose subject appears in this memory
            for subject, subject_triples in subject_index.items():
                if subject not in content_lower:
                    continue
                for t in subject_triples:
                    pred_text = t["predicate"].replace("_", " ")
                    if pred_text in content_lower:
                        if t["object"].lower() not in content_lower:
                            contradictions.append({
                                "memory_id": row["id"],
                                "memory_content": row["content"],
                                "graph_triple": f"{t['subject']} {t['predicate']} {t['object']}",
                                "type": "potential_contradiction",
                            })

        return contradictions

    def detect_surprises(self, new_content: str, threshold: float = 0.3) -> list[dict]:
        """
        Surprise detection: check if new information contradicts or significantly
        diverges from existing knowledge. Low similarity to related memories = surprise.

        Returns list of surprising findings for the agent to process.
        """
        surprises = []
        new_vec = embed(new_content)
        if not new_vec:
            return surprises

        # Find the most similar existing memories
        rows = self.conn.execute(
            """SELECT v.memory_id, v.memory_table, v.embedding, s.content
               FROM vectors v
               JOIN semantic s ON v.memory_id = s.id AND v.memory_table = 'semantic'
               WHERE s.agent_id = ?
               LIMIT 100""",
            (self.agent_id,)
        ).fetchall()

        for row in rows:
            sim = cosine_similarity(new_vec, row["embedding"])
            # High similarity but potentially contradictory content
            if 0.3 < sim < 0.7:
                surprises.append({
                    "existing_id": row["memory_id"],
                    "existing_content": row["content"],
                    "similarity": round(sim, 3),
                    "new_content": new_content,
                    "type": "surprise_divergence",
                })

        # Sort by most surprising (lowest similarity in the mid-range)
        surprises.sort(key=lambda x: abs(x["similarity"] - 0.5))
        return surprises[:5]

    def decay_audit(self) -> dict:
        """
        Audit memories by decay class and surface candidates for archival.
        """
        stats = {}

        # Count by decay class
        rows = self.conn.execute(
            """SELECT decay_class, COUNT(*) as c, AVG(importance) as avg_imp,
                      MIN(created_at) as oldest
               FROM semantic WHERE agent_id = ?
               GROUP BY decay_class""",
            (self.agent_id,)
        ).fetchall()

        for r in rows:
            stats[r["decay_class"] or "standard"] = {
                "count": r["c"],
                "avg_importance": round(r["avg_imp"], 3),
                "oldest": r["oldest"],
            }

        # Find low-importance, never-accessed memories as archive candidates
        archive_candidates = self.conn.execute(
            """SELECT id, content, importance, access_count, created_at
               FROM semantic
               WHERE agent_id = ? AND importance < 0.3 AND access_count = 0
               ORDER BY created_at ASC LIMIT 20""",
            (self.agent_id,)
        ).fetchall()

        stats["archive_candidates"] = len(archive_candidates)

        return stats
