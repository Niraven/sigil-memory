"""
Agent-to-Agent (A2A) Bridge for Sigil.
Event-driven sync between agents (Zo <> Hermes).
Sub-10s latency. Offline queue when partner is unavailable.
"""

import json
import time
import uuid
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _uid() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Event:
    id: str
    agent_id: str
    event_type: str
    payload: dict
    memory_id: Optional[str] = None
    memory_table: Optional[str] = None
    created_at: str = ""
    synced_by: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


class A2ABridge:
    """
    Event-driven bridge between agents.
    Uses the same SQLite database as the memory engine.
    Events are append-only; each agent marks events as consumed.
    """

    def __init__(self, conn: sqlite3.Connection, agent_id: str = "default",
                 event_file: Optional[str] = None):
        self.conn = conn
        self.agent_id = agent_id
        self.event_file = Path(event_file) if event_file else None
        self._handlers: dict[str, list[Callable]] = {}
        self._last_poll: str = "1970-01-01T00:00:00.000000"

    def emit(self, event_type: str, payload: dict,
             memory_id: Optional[str] = None,
             memory_table: Optional[str] = None) -> str:
        """Emit an event to the bus."""
        eid = f"evt_{_uid()}"
        now = _now()

        self.conn.execute(
            """INSERT INTO events (id, agent_id, event_type, payload,
               memory_id, memory_table, created_at, synced_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, self.agent_id, event_type, json.dumps(payload),
             memory_id, memory_table, now, json.dumps([self.agent_id]))
        )
        self.conn.commit()

        # Also write to JSONL file if configured (for cross-process sync)
        if self.event_file:
            self.event_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.event_file, "a") as f:
                event_data = {
                    "id": eid, "agent_id": self.agent_id,
                    "event_type": event_type, "payload": payload,
                    "memory_id": memory_id, "memory_table": memory_table,
                    "created_at": now
                }
                f.write(json.dumps(event_data) + "\n")

        # Fire local handlers
        self._fire_handlers(event_type, Event(
            id=eid, agent_id=self.agent_id, event_type=event_type,
            payload=payload, memory_id=memory_id, memory_table=memory_table,
            created_at=now, synced_by=[self.agent_id]
        ))

        return eid

    def pull(self, limit: int = 100) -> list[Event]:
        """Pull unsynced events from other agents."""
        rows = self.conn.execute(
            """SELECT * FROM events
               WHERE agent_id != ?
               AND NOT json_extract(synced_by, '$') LIKE ?
               ORDER BY created_at ASC
               LIMIT ?""",
            (self.agent_id, f'%"{self.agent_id}"%', limit)
        ).fetchall()

        events = []
        for r in rows:
            synced = json.loads(r["synced_by"])
            if self.agent_id in synced:
                continue

            event = Event(
                id=r["id"], agent_id=r["agent_id"],
                event_type=r["event_type"],
                payload=json.loads(r["payload"]),
                memory_id=r["memory_id"],
                memory_table=r["memory_table"],
                created_at=r["created_at"],
                synced_by=synced
            )
            events.append(event)

            # Mark as synced
            synced.append(self.agent_id)
            self.conn.execute(
                "UPDATE events SET synced_by = ? WHERE id = ?",
                (json.dumps(synced), r["id"])
            )

            # Fire handlers
            self._fire_handlers(event.event_type, event)

        self.conn.commit()
        return events

    def pull_from_file(self) -> list[Event]:
        """
        Pull events from the JSONL file (for cross-process sync).
        Used when agents can't share the same SQLite file.
        """
        if not self.event_file or not self.event_file.exists():
            return []

        events = []
        with open(self.event_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data["agent_id"] == self.agent_id:
                        continue
                    if data["created_at"] <= self._last_poll:
                        continue

                    event = Event(
                        id=data["id"],
                        agent_id=data["agent_id"],
                        event_type=data["event_type"],
                        payload=data["payload"],
                        memory_id=data.get("memory_id"),
                        memory_table=data.get("memory_table"),
                        created_at=data["created_at"]
                    )
                    events.append(event)
                    self._last_poll = max(self._last_poll, data["created_at"])
                    self._fire_handlers(event.event_type, event)
                except (json.JSONDecodeError, KeyError):
                    continue

        return events

    def on(self, event_type: str, handler: Callable[[Event], None]):
        """Register a handler for an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def _fire_handlers(self, event_type: str, event: Event):
        """Fire registered handlers for an event type."""
        for handler in self._handlers.get(event_type, []):
            try:
                handler(event)
            except Exception:
                pass  # Don't let handler errors break the bridge
        # Also fire wildcard handlers
        for handler in self._handlers.get("*", []):
            try:
                handler(event)
            except Exception:
                pass

    def recent(self, limit: int = 20, event_type: Optional[str] = None) -> list[Event]:
        """Get recent events."""
        if event_type:
            rows = self.conn.execute(
                """SELECT * FROM events WHERE event_type = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (event_type, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM events ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()

        return [Event(
            id=r["id"], agent_id=r["agent_id"],
            event_type=r["event_type"],
            payload=json.loads(r["payload"]),
            memory_id=r["memory_id"],
            memory_table=r["memory_table"],
            created_at=r["created_at"],
            synced_by=json.loads(r["synced_by"])
        ) for r in rows]

    def cleanup(self, older_than_days: int = 30):
        """Remove old synced events to keep the DB lean."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f")
        self.conn.execute(
            "DELETE FROM events WHERE created_at < ?",
            (cutoff,)
        )
        self.conn.commit()

    def stats(self) -> dict:
        """Bridge statistics."""
        total = self.conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]
        by_agent = self.conn.execute(
            "SELECT agent_id, COUNT(*) as c FROM events GROUP BY agent_id"
        ).fetchall()
        by_type = self.conn.execute(
            "SELECT event_type, COUNT(*) as c FROM events GROUP BY event_type ORDER BY c DESC LIMIT 10"
        ).fetchall()

        return {
            "total_events": total,
            "by_agent": {r["agent_id"]: r["c"] for r in by_agent},
            "by_type": {r["event_type"]: r["c"] for r in by_type},
        }
