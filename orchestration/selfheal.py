"""
Self-Healing System for Sigil.
Inspired by Zouroboros's Health Council but simplified to what actually matters.

Three capabilities:
1. Stagnation detection — catch loops, repetitive output, progress plateaus
2. Circuit breaker management — track and recover from failure patterns
3. Capability gap tracking — surface repeated failures for skill development
"""

import json
import time
import sqlite3
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from collections import defaultdict


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


class StagnationDetector:
    """
    Detects when an agent is looping, producing repetitive output,
    or making no progress.
    """

    def __init__(self, max_history: int = 20):
        self._output_hashes: list[str] = []
        self._progress_markers: list[float] = []
        self.max_history = max_history

    def check_output(self, output: str) -> dict:
        """
        Check if output is repetitive or stagnant.
        Returns signals dict with booleans.
        """
        h = hashlib.md5(output.encode()).hexdigest()[:12]

        signals = {
            "is_repetitive": False,
            "is_empty": len(output.strip()) < 10,
            "repetition_count": 0,
            "recommendation": None,
        }

        # Check for exact repeats
        repeat_count = self._output_hashes.count(h)
        if repeat_count >= 2:
            signals["is_repetitive"] = True
            signals["repetition_count"] = repeat_count
            signals["recommendation"] = "Output repeated 3+ times. Suggest different approach."

        self._output_hashes.append(h)
        if len(self._output_hashes) > self.max_history:
            self._output_hashes = self._output_hashes[-self.max_history:]

        return signals

    def check_progress(self, progress_value: float) -> dict:
        """
        Check if progress has plateaued.
        progress_value: 0.0 to 1.0 representing task completion.
        """
        self._progress_markers.append(progress_value)
        if len(self._progress_markers) > self.max_history:
            self._progress_markers = self._progress_markers[-self.max_history:]

        signals = {
            "is_plateau": False,
            "plateau_duration": 0,
            "recommendation": None,
        }

        if len(self._progress_markers) >= 5:
            recent = self._progress_markers[-5:]
            if max(recent) - min(recent) < 0.01:
                signals["is_plateau"] = True
                signals["plateau_duration"] = 5
                signals["recommendation"] = "No progress in 5 checks. Re-evaluate approach."

        return signals

    def reset(self):
        self._output_hashes = []
        self._progress_markers = []


class CapabilityTracker:
    """
    Tracks repeated failures to surface capability gaps.
    When the same type of failure happens 2+ times, it gets flagged
    for skill development or rule creation.
    """

    def __init__(self, conn: sqlite3.Connection, agent_id: str = "default"):
        self.conn = conn
        self.agent_id = agent_id
        self._ensure_table()

    def _ensure_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS capability_gaps (
                id TEXT PRIMARY KEY,
                error_pattern TEXT NOT NULL,
                occurrence_count INTEGER DEFAULT 1,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                contexts TEXT DEFAULT '[]',
                status TEXT DEFAULT 'open',
                resolution TEXT,
                agent_id TEXT DEFAULT 'default'
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gaps_agent ON capability_gaps(agent_id)")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_gaps_status ON capability_gaps(status)")
        self.conn.commit()

    def record_failure(self, error_pattern: str, context: str = "") -> dict:
        """
        Record a failure. If this pattern has been seen before, increment count.
        Returns gap info including whether it should be surfaced to the user.
        """
        now = _now()
        # Normalize the error pattern
        normalized = error_pattern.lower().strip()[:200]
        pattern_hash = hashlib.md5(normalized.encode()).hexdigest()[:12]

        existing = self.conn.execute(
            "SELECT * FROM capability_gaps WHERE id = ? AND agent_id = ?",
            (pattern_hash, self.agent_id)
        ).fetchone()

        if existing:
            contexts = json.loads(existing["contexts"])
            contexts.append({"context": context[:200], "when": now})
            contexts = contexts[-10:]  # Keep last 10

            self.conn.execute(
                """UPDATE capability_gaps SET occurrence_count = occurrence_count + 1,
                   last_seen = ?, contexts = ? WHERE id = ?""",
                (now, json.dumps(contexts), pattern_hash)
            )
            self.conn.commit()

            count = existing["occurrence_count"] + 1
            return {
                "gap_id": pattern_hash,
                "pattern": normalized,
                "count": count,
                "should_surface": count >= 2,
                "recommendation": (
                    f"This failure has occurred {count} times. "
                    "Consider creating a skill or rule to handle it."
                ) if count >= 2 else None,
            }
        else:
            self.conn.execute(
                """INSERT INTO capability_gaps
                   (id, error_pattern, first_seen, last_seen, contexts, agent_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (pattern_hash, normalized, now, now,
                 json.dumps([{"context": context[:200], "when": now}]),
                 self.agent_id)
            )
            self.conn.commit()

            return {
                "gap_id": pattern_hash,
                "pattern": normalized,
                "count": 1,
                "should_surface": False,
                "recommendation": None,
            }

    def resolve(self, gap_id: str, resolution: str) -> bool:
        """Mark a capability gap as resolved."""
        result = self.conn.execute(
            "UPDATE capability_gaps SET status = 'resolved', resolution = ? WHERE id = ?",
            (resolution, gap_id)
        )
        self.conn.commit()
        return result.rowcount > 0

    def open_gaps(self, min_count: int = 2) -> list[dict]:
        """Get all open capability gaps above the threshold."""
        rows = self.conn.execute(
            """SELECT * FROM capability_gaps
               WHERE agent_id = ? AND status = 'open'
               AND occurrence_count >= ?
               ORDER BY occurrence_count DESC""",
            (self.agent_id, min_count)
        ).fetchall()

        return [{
            "gap_id": r["id"],
            "pattern": r["error_pattern"],
            "count": r["occurrence_count"],
            "first_seen": r["first_seen"],
            "last_seen": r["last_seen"],
            "contexts": json.loads(r["contexts"])[-3:],
        } for r in rows]

    def weekly_report(self) -> dict:
        """Generate weekly capability gap report."""
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f")

        new_gaps = self.conn.execute(
            """SELECT COUNT(*) as c FROM capability_gaps
               WHERE agent_id = ? AND first_seen > ?""",
            (self.agent_id, week_ago)
        ).fetchone()["c"]

        recurring = self.conn.execute(
            """SELECT COUNT(*) as c FROM capability_gaps
               WHERE agent_id = ? AND status = 'open' AND occurrence_count >= 3""",
            (self.agent_id,)
        ).fetchone()["c"]

        resolved = self.conn.execute(
            """SELECT COUNT(*) as c FROM capability_gaps
               WHERE agent_id = ? AND status = 'resolved'
               AND last_seen > ?""",
            (self.agent_id, week_ago)
        ).fetchone()["c"]

        return {
            "new_gaps_this_week": new_gaps,
            "recurring_unresolved": recurring,
            "resolved_this_week": resolved,
            "open_gaps": self.open_gaps(min_count=2),
        }


class SelfHealEngine:
    """
    Unified self-healing engine combining stagnation detection,
    capability tracking, and health monitoring.
    """

    def __init__(self, conn: sqlite3.Connection, agent_id: str = "default"):
        self.stagnation = StagnationDetector()
        self.capabilities = CapabilityTracker(conn, agent_id)
        self.agent_id = agent_id
        self._health_checks: dict[str, dict] = {}

    def check(self, output: str = "", progress: float = -1,
              error: str = "", context: str = "") -> dict:
        """
        Run all health checks in one call.
        Returns combined signals and recommendations.
        """
        signals = {"healthy": True, "issues": [], "recommendations": []}

        # Stagnation
        if output:
            stag = self.stagnation.check_output(output)
            if stag["is_repetitive"]:
                signals["healthy"] = False
                signals["issues"].append("repetitive_output")
                signals["recommendations"].append(stag["recommendation"])
            if stag["is_empty"]:
                signals["healthy"] = False
                signals["issues"].append("empty_output")

        # Progress
        if progress >= 0:
            prog = self.stagnation.check_progress(progress)
            if prog["is_plateau"]:
                signals["healthy"] = False
                signals["issues"].append("progress_plateau")
                signals["recommendations"].append(prog["recommendation"])

        # Capability gaps
        if error:
            gap = self.capabilities.record_failure(error, context)
            if gap["should_surface"]:
                signals["healthy"] = False
                signals["issues"].append("recurring_failure")
                signals["recommendations"].append(gap["recommendation"])

        return signals

    def report(self) -> dict:
        """Full health report."""
        return {
            "capability_gaps": self.capabilities.weekly_report(),
            "agent_id": self.agent_id,
        }
