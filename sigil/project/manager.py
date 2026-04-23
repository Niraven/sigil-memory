"""
Project Management Layer for Sigil.
Task tracking, milestones, sprint cycles, dependency management.
Auto-surfaces blockers and progress to PKA.
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
class Project:
    id: str
    name: str
    description: str = ""
    status: str = "active"
    milestone: str = ""
    deadline: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class ProjectTask:
    id: str
    project_id: str
    title: str
    description: str = ""
    status: str = "pending"
    priority: str = "medium"
    assignee: str = ""
    depends_on: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    completed_at: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class ProjectManager:
    """
    Project and task management built into Sigil.
    """

    def __init__(self, conn: sqlite3.Connection, agent_id: str = "default"):
        self.conn = conn
        self.agent_id = agent_id

    def create(self, name: str, description: str = "",
               milestone: str = "", deadline: Optional[str] = None,
               metadata: Optional[dict] = None) -> str:
        """Create a new project."""
        pid = f"proj_{_uid()}"
        now = _now()
        meta = json.dumps(metadata or {})

        self.conn.execute(
            """INSERT INTO projects (id, name, description, status, milestone,
               deadline, created_at, updated_at, metadata)
               VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
            (pid, name, description, milestone, deadline, now, now, meta)
        )
        self.conn.commit()
        return pid

    def get(self, project_id: str) -> Optional[Project]:
        """Get project by ID."""
        row = self.conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not row:
            return None
        return Project(**{k: row[k] for k in row.keys() if k != "metadata"},
                       metadata=json.loads(row["metadata"]))

    def find(self, name: str) -> Optional[Project]:
        """Find project by name."""
        row = self.conn.execute(
            "SELECT * FROM projects WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            return None
        return Project(**{k: row[k] for k in row.keys() if k != "metadata"},
                       metadata=json.loads(row["metadata"]))

    def list_projects(self, status: str = "active") -> list[Project]:
        """List projects by status."""
        rows = self.conn.execute(
            "SELECT * FROM projects WHERE status = ? ORDER BY updated_at DESC",
            (status,)
        ).fetchall()
        return [Project(**{k: r[k] for k in r.keys() if k != "metadata"},
                        metadata=json.loads(r["metadata"])) for r in rows]

    def update(self, project_id: str, **kwargs) -> bool:
        """Update project fields."""
        if not kwargs:
            return False
        now = _now()
        sets = ["updated_at = ?"]
        params = [now]
        for k, v in kwargs.items():
            if k in ("name", "description", "status", "milestone", "deadline"):
                sets.append(f"{k} = ?")
                params.append(v)
            elif k == "metadata":
                sets.append("metadata = ?")
                params.append(json.dumps(v))

        params.append(project_id)
        self.conn.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", params
        )
        self.conn.commit()
        return True

    # ── Tasks ─────────────────────────────────────────────────────

    def add_task(self, project_id: str, title: str, description: str = "",
                 priority: str = "medium", assignee: str = "",
                 depends_on: Optional[list[str]] = None,
                 metadata: Optional[dict] = None) -> str:
        """Add a task to a project."""
        tid = f"task_{_uid()}"
        now = _now()
        deps = json.dumps(depends_on or [])
        meta = json.dumps(metadata or {})

        self.conn.execute(
            """INSERT INTO tasks (id, project_id, title, description, status,
               priority, assignee, depends_on, created_at, updated_at, metadata)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)""",
            (tid, project_id, title, description, priority, assignee, deps, now, now, meta)
        )
        self.conn.commit()
        return tid

    def update_task(self, task_id: str, **kwargs) -> bool:
        """Update task fields."""
        now = _now()
        sets = ["updated_at = ?"]
        params = [now]

        for k, v in kwargs.items():
            if k in ("title", "description", "status", "priority", "assignee"):
                sets.append(f"{k} = ?")
                params.append(v)
                if k == "status" and v == "completed":
                    sets.append("completed_at = ?")
                    params.append(now)
            elif k == "depends_on":
                sets.append("depends_on = ?")
                params.append(json.dumps(v))
            elif k == "metadata":
                sets.append("metadata = ?")
                params.append(json.dumps(v))

        params.append(task_id)
        self.conn.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params
        )
        self.conn.commit()
        return True

    def get_task(self, task_id: str) -> Optional[ProjectTask]:
        """Get task by ID."""
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def list_tasks(self, project_id: str, status: Optional[str] = None) -> list[ProjectTask]:
        """List tasks for a project."""
        if status:
            rows = self.conn.execute(
                """SELECT * FROM tasks WHERE project_id = ? AND status = ?
                   ORDER BY
                     CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                     WHEN 'medium' THEN 2 ELSE 3 END,
                     created_at ASC""",
                (project_id, status)
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM tasks WHERE project_id = ?
                   ORDER BY
                     CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                     WHEN 'medium' THEN 2 ELSE 3 END,
                     created_at ASC""",
                (project_id,)
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def _row_to_task(self, row) -> ProjectTask:
        return ProjectTask(
            id=row["id"], project_id=row["project_id"],
            title=row["title"], description=row["description"] or "",
            status=row["status"], priority=row["priority"],
            assignee=row["assignee"] or "",
            depends_on=json.loads(row["depends_on"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            metadata=json.loads(row["metadata"])
        )

    # ── Status & Analytics ────────────────────────────────────────

    def status(self, project_id: str) -> dict:
        """Get comprehensive project status."""
        project = self.get(project_id)
        if not project:
            return {"error": "Project not found"}

        tasks = self.list_tasks(project_id)
        by_status = {}
        by_assignee = {}
        blockers = []

        for t in tasks:
            by_status[t.status] = by_status.get(t.status, 0) + 1
            if t.assignee:
                if t.assignee not in by_assignee:
                    by_assignee[t.assignee] = {"pending": 0, "in_progress": 0, "completed": 0}
                by_assignee[t.assignee][t.status] = by_assignee[t.assignee].get(t.status, 0) + 1

            # Check for blocked tasks (deps not completed)
            if t.status == "pending" and t.depends_on:
                for dep_id in t.depends_on:
                    dep = self.get_task(dep_id)
                    if dep and dep.status != "completed":
                        blockers.append({
                            "task": t.title,
                            "blocked_by": dep.title,
                            "blocker_status": dep.status
                        })

        total = len(tasks)
        completed = by_status.get("completed", 0)
        progress = (completed / total * 100) if total > 0 else 0

        return {
            "project": project.name,
            "status": project.status,
            "milestone": project.milestone,
            "deadline": project.deadline,
            "progress": round(progress, 1),
            "total_tasks": total,
            "by_status": by_status,
            "by_assignee": by_assignee,
            "blockers": blockers,
            "next_actions": self._next_actions(tasks),
        }

    def _next_actions(self, tasks: list[ProjectTask]) -> list[str]:
        """Determine the next actionable tasks."""
        completed_ids = {t.id for t in tasks if t.status == "completed"}
        ready = []
        for t in tasks:
            if t.status != "pending":
                continue
            deps_met = all(d in completed_ids for d in t.depends_on)
            if deps_met:
                ready.append(f"[{t.priority}] {t.title}" +
                             (f" (assigned: {t.assignee})" if t.assignee else ""))
        return ready[:5]

    def active_work(self) -> list[dict]:
        """Get all in-progress work across all projects."""
        rows = self.conn.execute(
            """SELECT t.*, p.name as project_name FROM tasks t
               JOIN projects p ON t.project_id = p.id
               WHERE t.status = 'in_progress'
               ORDER BY
                 CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                 WHEN 'medium' THEN 2 ELSE 3 END""",
        ).fetchall()
        return [{
            "task": r["title"],
            "project": r["project_name"],
            "assignee": r["assignee"],
            "priority": r["priority"],
            "since": r["updated_at"],
        } for r in rows]
