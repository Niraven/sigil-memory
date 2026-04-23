"""
Proactive Knowledge Activation (PKA) — The "right brain" of Sigil.
Inspired by Zouroboros PKA concept. Fires automatically on session start.
Anticipates what the agent needs to know before the user even asks.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional


class ProactiveActivation:
    """
    Generates context briefings by pulling relevant memories,
    open loops, recent episodes, and cross-domain insights.
    """

    def __init__(self, memory_engine, knowledge_graph,
                 lookback_days: int = 14, max_brief_items: int = 10):
        self.memory = memory_engine
        self.graph = knowledge_graph
        self.lookback_days = lookback_days
        self.max_items = max_brief_items

    def activate(self, persona: str = "default",
                 session_context: str = "",
                 active_projects: Optional[list[str]] = None) -> dict:
        """
        Generate a proactive briefing. Returns structured context
        that should be injected before the first LLM call.
        """
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=self.lookback_days)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f")

        brief = {
            "generated_at": now.isoformat(),
            "persona": persona,
            "sections": {}
        }

        # 1. Recent episodes (what happened lately)
        recent_episodes = self._recent_episodes(cutoff)
        if recent_episodes:
            brief["sections"]["recent_activity"] = {
                "label": "What happened recently",
                "items": recent_episodes
            }

        # 2. Open loops (unfinished work, pending decisions)
        open_loops = self._open_loops()
        if open_loops:
            brief["sections"]["open_loops"] = {
                "label": "Open loops and pending items",
                "items": open_loops
            }

        # 3. Active project status
        if active_projects:
            project_status = self._project_status(active_projects)
            if project_status:
                brief["sections"]["projects"] = {
                    "label": "Active project status",
                    "items": project_status
                }

        # 4. Context-relevant memories (if session has context)
        if session_context:
            relevant = self._context_relevant(session_context)
            if relevant:
                brief["sections"]["relevant_context"] = {
                    "label": "Relevant to current context",
                    "items": relevant
                }

        # 5. Cross-domain insights (knowledge that connects different areas)
        cross_domain = self._cross_domain_insights(persona)
        if cross_domain:
            brief["sections"]["cross_domain"] = {
                "label": "Cross-domain connections",
                "items": cross_domain
            }

        # 6. Corrections and learnings (don't repeat past mistakes)
        corrections = self._recent_corrections(cutoff)
        if corrections:
            brief["sections"]["corrections"] = {
                "label": "Recent corrections (avoid repeating)",
                "items": corrections
            }

        # Generate summary
        brief["summary"] = self._generate_summary(brief["sections"])
        brief["token_estimate"] = self._estimate_tokens(brief)

        return brief

    def _recent_episodes(self, cutoff: str) -> list[dict]:
        """Get recent episodic memories."""
        conn = self.memory._get_conn()
        rows = conn.execute(
            """SELECT id, summary, outcome, importance, created_at
               FROM episodic
               WHERE agent_id = ? AND created_at > ?
               ORDER BY importance DESC, created_at DESC
               LIMIT ?""",
            (self.memory.agent_id, cutoff, self.max_items)
        ).fetchall()
        return [{"summary": r["summary"], "outcome": r["outcome"] or "pending",
                 "importance": r["importance"], "when": r["created_at"]}
                for r in rows]

    def _open_loops(self) -> list[dict]:
        """Find unresolved episodic events and pending tasks."""
        conn = self.memory._get_conn()
        items = []

        # Episodic memories with no outcome or pending outcome
        episodes = conn.execute(
            """SELECT summary, created_at FROM episodic
               WHERE agent_id = ? AND (outcome IS NULL OR outcome = '' OR outcome = 'pending')
               ORDER BY importance DESC, created_at DESC
               LIMIT ?""",
            (self.memory.agent_id, 5)
        ).fetchall()
        for e in episodes:
            items.append({"type": "episode", "summary": e["summary"],
                          "since": e["created_at"]})

        # Pending tasks (filter by assignee matching agent_id, or unassigned)
        tasks = conn.execute(
            """SELECT title, priority, created_at FROM tasks
               WHERE status IN ('pending', 'in_progress')
               AND (assignee = ? OR assignee = '' OR assignee IS NULL)
               ORDER BY
                   CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                   WHEN 'medium' THEN 2 ELSE 3 END,
                   created_at ASC
               LIMIT ?""",
            (self.memory.agent_id, 5)
        ).fetchall()
        for t in tasks:
            items.append({"type": "task", "title": t["title"],
                          "priority": t["priority"], "since": t["created_at"]})

        return items

    def _project_status(self, project_names: list[str]) -> list[dict]:
        """Get status of specified projects."""
        conn = self.memory._get_conn()
        items = []
        for name in project_names:
            project = conn.execute(
                "SELECT * FROM projects WHERE name = ? AND status = 'active'",
                (name,)
            ).fetchone()
            if not project:
                continue

            task_counts = conn.execute(
                """SELECT status, COUNT(*) as c FROM tasks
                   WHERE project_id = ? GROUP BY status""",
                (project["id"],)
            ).fetchall()
            status_map = {r["status"]: r["c"] for r in task_counts}

            items.append({
                "project": name,
                "milestone": project["milestone"],
                "deadline": project["deadline"],
                "tasks": status_map
            })
        return items

    def _context_relevant(self, context: str) -> list[dict]:
        """Find memories relevant to the current session context."""
        results = self.memory.recall(context, top_k=5,
                                     tables=["semantic", "episodic", "procedural"])
        return [{"content": r.content, "type": r.table,
                 "score": round(r.score, 3)} for r in results]

    def _cross_domain_insights(self, persona: str) -> list[dict]:
        """
        Find knowledge graph connections that bridge different domains.
        This is the PKA magic — surfacing things the agent wouldn't
        think to look for.
        """
        items = []

        # Get high-degree entities (they connect many things)
        conn = self.memory._get_conn()
        entities = conn.execute(
            """SELECT subject, COUNT(*) as degree FROM triples
               WHERE agent_id = ? AND valid_until IS NULL
               GROUP BY subject
               HAVING degree >= 3
               ORDER BY degree DESC
               LIMIT 5""",
            (self.memory.agent_id,)
        ).fetchall()

        for ent in entities:
            triples = self.graph.query(subject=ent["subject"], limit=5)
            if len(triples) >= 2:
                connections = [f"{t.predicate} {t.object}" for t in triples[:3]]
                items.append({
                    "entity": ent["subject"],
                    "connections": connections,
                    "significance": f"Hub entity with {ent['degree']} connections"
                })

        return items[:3]

    def _recent_corrections(self, cutoff: str) -> list[dict]:
        """Find recent corrections/learnings to avoid repeating mistakes."""
        results = self.memory.recall(
            "correction mistake error wrong fix",
            top_k=3,
            tables=["semantic", "episodic"]
        )
        return [{"content": r.content, "type": r.table}
                for r in results if r.score > 0.3]

    def _generate_summary(self, sections: dict) -> str:
        """Generate a concise text summary of the briefing."""
        parts = []
        for key, section in sections.items():
            count = len(section["items"])
            parts.append(f"{section['label']}: {count} items")
        return "; ".join(parts) if parts else "No active context found."

    def _estimate_tokens(self, brief: dict) -> int:
        """Rough token estimate for the briefing."""
        text = json.dumps(brief)
        return len(text) // 4  # ~4 chars per token estimate

    def to_prompt(self, brief: dict) -> str:
        """Convert briefing to injectable prompt text."""
        lines = ["[SIGIL ACTIVATION BRIEF]", ""]

        for key, section in brief.get("sections", {}).items():
            lines.append(f"## {section['label']}")
            for item in section["items"]:
                if "summary" in item:
                    outcome = f" [{item.get('outcome', 'pending')}]" if item.get("outcome") else ""
                    lines.append(f"- {item['summary']}{outcome}")
                elif "title" in item:
                    lines.append(f"- [{item.get('priority', 'medium')}] {item['title']}")
                elif "content" in item:
                    lines.append(f"- {item['content']}")
                elif "entity" in item:
                    conns = ", ".join(item.get("connections", []))
                    lines.append(f"- {item['entity']}: {conns}")
                elif "project" in item:
                    tasks = item.get("tasks", {})
                    done = tasks.get("completed", 0)
                    total = sum(tasks.values())
                    lines.append(f"- {item['project']}: {done}/{total} tasks done")
            lines.append("")

        lines.append(f"[~{brief.get('token_estimate', 0)} tokens]")
        return "\n".join(lines)
