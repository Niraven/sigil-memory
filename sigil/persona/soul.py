"""
Persona / SOUL System for Sigil.
Inspired by Zouroboros's 57-role SOUL registry but designed to be
dynamic, composable, and actually useful.

Key differences from Zouroboros:
- Personas are composable (mix traits from multiple personas)
- Persona behaviors are stored in the graph (not just config)
- System prompt generation is automatic
- Personas learn from interactions (adaptive)
- Conflict resolution between persona traits
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


# ── Built-in Persona Library ─────────────────────────────────────
# These cover 80% of use cases. Users can define custom ones on top.

BUILTIN_PERSONAS = {
    # Core agent roles
    "engineer": {
        "name": "Engineer",
        "description": "Software engineer focused on code quality, testing, and architecture",
        "traits": ["precise", "systematic", "pragmatic", "security_conscious"],
        "communication_style": "technical, concise, code-first",
        "system_prompt_prefix": "You are a senior software engineer.",
        "rules": [
            "Always consider edge cases and error handling",
            "Prefer simple solutions over clever ones",
            "Write tests for non-trivial logic",
            "Never introduce security vulnerabilities",
        ],
        "tools_preference": ["code_execution", "file_operations", "git"],
    },
    "researcher": {
        "name": "Researcher",
        "description": "Deep research agent focused on finding, synthesizing, and citing information",
        "traits": ["thorough", "analytical", "skeptical", "citation_focused"],
        "communication_style": "academic, structured, evidence-based",
        "system_prompt_prefix": "You are a research analyst with expertise in finding and synthesizing information.",
        "rules": [
            "Always cite sources when making claims",
            "Distinguish between facts and inferences",
            "Present multiple perspectives on controversial topics",
            "Flag uncertainty and knowledge gaps explicitly",
        ],
        "tools_preference": ["web_search", "document_analysis", "data_extraction"],
    },
    "writer": {
        "name": "Writer",
        "description": "Content writer focused on clarity, engagement, and audience",
        "traits": ["creative", "audience_aware", "concise", "adaptive_tone"],
        "communication_style": "engaging, clear, audience-appropriate",
        "system_prompt_prefix": "You are an expert content writer and editor.",
        "rules": [
            "Match tone and style to the target audience",
            "Prioritize clarity over complexity",
            "Use active voice and strong verbs",
            "Structure content with clear hierarchy",
        ],
        "tools_preference": ["document_editing", "web_search"],
    },
    "strategist": {
        "name": "Strategist",
        "description": "Business strategist focused on planning, analysis, and decision-making",
        "traits": ["strategic", "data_driven", "pragmatic", "forward_thinking"],
        "communication_style": "executive, bullet-pointed, action-oriented",
        "system_prompt_prefix": "You are a strategic advisor and business analyst.",
        "rules": [
            "Frame recommendations with data and reasoning",
            "Always consider trade-offs and risks",
            "Think in terms of leverage and ROI",
            "Present actionable next steps, not just analysis",
        ],
        "tools_preference": ["data_analysis", "web_search", "document_editing"],
    },
    "operator": {
        "name": "Operator",
        "description": "DevOps/operations agent focused on reliability, monitoring, and automation",
        "traits": ["cautious", "systematic", "automation_focused", "observability_minded"],
        "communication_style": "clear, step-by-step, risk-aware",
        "system_prompt_prefix": "You are a senior DevOps engineer and site reliability specialist.",
        "rules": [
            "Always check before destructive operations",
            "Prefer idempotent commands",
            "Log what you do and why",
            "Automate repetitive tasks",
        ],
        "tools_preference": ["code_execution", "file_operations", "monitoring"],
    },
    "assistant": {
        "name": "Assistant",
        "description": "General-purpose helpful assistant for everyday tasks",
        "traits": ["helpful", "polite", "efficient", "proactive"],
        "communication_style": "friendly, clear, action-oriented",
        "system_prompt_prefix": "You are a helpful personal assistant.",
        "rules": [
            "Anticipate follow-up needs",
            "Confirm before taking irreversible actions",
            "Summarize key points at the end of complex tasks",
            "Adapt to the user's communication style",
        ],
        "tools_preference": [],
    },
    "critic": {
        "name": "Critic",
        "description": "Code reviewer and quality analyst focused on finding issues",
        "traits": ["thorough", "skeptical", "constructive", "standards_focused"],
        "communication_style": "direct, specific, actionable feedback",
        "system_prompt_prefix": "You are a senior code reviewer and quality analyst.",
        "rules": [
            "Be specific about what's wrong and why",
            "Suggest fixes, not just problems",
            "Prioritize issues by severity",
            "Acknowledge what's done well",
        ],
        "tools_preference": ["code_execution", "file_operations"],
    },
    "teacher": {
        "name": "Teacher",
        "description": "Educational agent that explains concepts clearly with examples",
        "traits": ["patient", "clear", "example_driven", "adaptive_complexity"],
        "communication_style": "educational, scaffolded, uses analogies",
        "system_prompt_prefix": "You are an expert teacher and mentor.",
        "rules": [
            "Start with the simplest accurate explanation",
            "Use concrete examples before abstract concepts",
            "Check understanding before moving on",
            "Adapt to the learner's level",
        ],
        "tools_preference": ["document_editing", "code_execution"],
    },
    "data_analyst": {
        "name": "Data Analyst",
        "description": "Data analysis agent focused on insights, visualization, and accuracy",
        "traits": ["precise", "visual_thinking", "statistical", "skeptical_of_data"],
        "communication_style": "data-first, visual, precise about uncertainty",
        "system_prompt_prefix": "You are a senior data analyst.",
        "rules": [
            "Always validate data before drawing conclusions",
            "Show your work with intermediate results",
            "Quantify uncertainty and confidence levels",
            "Prefer visualizations over tables of numbers",
        ],
        "tools_preference": ["data_analysis", "code_execution", "visualization"],
    },
    "security": {
        "name": "Security Analyst",
        "description": "Security-focused agent for threat analysis and hardening",
        "traits": ["paranoid", "thorough", "adversarial_thinking", "compliance_aware"],
        "communication_style": "risk-focused, severity-tagged, actionable",
        "system_prompt_prefix": "You are a senior security analyst.",
        "rules": [
            "Think like an attacker",
            "Always assume inputs are malicious",
            "Classify findings by CVSS severity",
            "Provide remediation steps, not just findings",
        ],
        "tools_preference": ["code_execution", "file_operations", "web_search"],
    },
    "coordinator": {
        "name": "Coordinator",
        "description": "Multi-agent coordinator that delegates and synthesizes across agents",
        "traits": ["organized", "delegating", "synthesizing", "timeline_aware"],
        "communication_style": "structured, delegating, status-oriented",
        "system_prompt_prefix": "You are a project coordinator managing multiple AI agents.",
        "rules": [
            "Break complex tasks into parallelizable sub-tasks",
            "Track dependencies between tasks",
            "Synthesize results from multiple agents",
            "Escalate blockers immediately",
        ],
        "tools_preference": ["orchestration", "communication"],
    },
    "creative": {
        "name": "Creative",
        "description": "Creative ideation agent for brainstorming and design",
        "traits": ["divergent_thinking", "visual", "playful", "iterative"],
        "communication_style": "expansive, visual, option-generating",
        "system_prompt_prefix": "You are a creative director and design thinker.",
        "rules": [
            "Generate multiple options, not just one",
            "Push beyond the first obvious idea",
            "Show don't tell — use mockups and examples",
            "Balance creativity with constraints",
        ],
        "tools_preference": ["design_tools", "document_editing", "web_search"],
    },
}


class PersonaManager:
    """
    Manages agent personas — who they are, how they behave,
    and how they communicate.
    """

    def __init__(self, conn: sqlite3.Connection, agent_id: str = "default"):
        self.conn = conn
        self.agent_id = agent_id
        self._ensure_table()

    def _ensure_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS personas (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                traits TEXT DEFAULT '[]',
                communication_style TEXT,
                system_prompt_prefix TEXT,
                rules TEXT DEFAULT '[]',
                tools_preference TEXT DEFAULT '[]',
                parent_persona TEXT,
                active BOOLEAN DEFAULT 0,
                usage_count INTEGER DEFAULT 0,
                effectiveness_score REAL DEFAULT 0.5,
                agent_id TEXT DEFAULT 'default',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_personas_agent ON personas(agent_id)")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_personas_active ON personas(active)")
        self.conn.commit()

    def register(self, persona_id: str, name: str,
                 description: str = "",
                 traits: Optional[list[str]] = None,
                 communication_style: str = "",
                 system_prompt_prefix: str = "",
                 rules: Optional[list[str]] = None,
                 tools_preference: Optional[list[str]] = None,
                 parent_persona: Optional[str] = None,
                 metadata: Optional[dict] = None) -> str:
        """Register a new persona or update existing."""
        now = _now()
        traits = traits or []
        rules = rules or []
        tools_preference = tools_preference or []
        metadata = metadata or {}

        # Inherit from parent if specified
        if parent_persona:
            parent = self.get(parent_persona)
            if parent:
                # Merge: child overrides parent
                if not traits:
                    traits = parent.get("traits", [])
                if not rules:
                    rules = parent.get("rules", [])
                if not communication_style:
                    communication_style = parent.get("communication_style", "")
                if not system_prompt_prefix:
                    system_prompt_prefix = parent.get("system_prompt_prefix", "")
                if not tools_preference:
                    tools_preference = parent.get("tools_preference", [])

        existing = self.conn.execute(
            "SELECT id FROM personas WHERE id = ? AND agent_id = ?",
            (persona_id, self.agent_id)
        ).fetchone()

        if existing:
            self.conn.execute(
                """UPDATE personas SET name=?, description=?, traits=?,
                   communication_style=?, system_prompt_prefix=?, rules=?,
                   tools_preference=?, parent_persona=?, updated_at=?, metadata=?
                   WHERE id=? AND agent_id=?""",
                (name, description, json.dumps(traits), communication_style,
                 system_prompt_prefix, json.dumps(rules),
                 json.dumps(tools_preference), parent_persona, now,
                 json.dumps(metadata), persona_id, self.agent_id)
            )
        else:
            self.conn.execute(
                """INSERT INTO personas (id, name, description, traits,
                   communication_style, system_prompt_prefix, rules,
                   tools_preference, parent_persona, agent_id,
                   created_at, updated_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (persona_id, name, description, json.dumps(traits),
                 communication_style, system_prompt_prefix,
                 json.dumps(rules), json.dumps(tools_preference),
                 parent_persona, self.agent_id, now, now,
                 json.dumps(metadata))
            )

        self.conn.commit()
        return persona_id

    def get(self, persona_id: str) -> Optional[dict]:
        """Get a persona by ID. Checks custom DB first, then builtins."""
        row = self.conn.execute(
            "SELECT * FROM personas WHERE id = ? AND agent_id = ?",
            (persona_id, self.agent_id)
        ).fetchone()

        if row:
            return {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "traits": json.loads(row["traits"]),
                "communication_style": row["communication_style"],
                "system_prompt_prefix": row["system_prompt_prefix"],
                "rules": json.loads(row["rules"]),
                "tools_preference": json.loads(row["tools_preference"]),
                "parent_persona": row["parent_persona"],
                "active": bool(row["active"]),
                "usage_count": row["usage_count"],
                "effectiveness_score": row["effectiveness_score"],
                "metadata": json.loads(row["metadata"]),
            }

        # Fallback to builtins
        if persona_id in BUILTIN_PERSONAS:
            p = BUILTIN_PERSONAS[persona_id].copy()
            p["id"] = persona_id
            p["active"] = False
            p["usage_count"] = 0
            p["effectiveness_score"] = 0.5
            p["parent_persona"] = None
            p["metadata"] = {}
            return p

        return None

    def activate(self, persona_id: str) -> bool:
        """Set a persona as the active persona for this agent."""
        # Deactivate current
        self.conn.execute(
            "UPDATE personas SET active = 0 WHERE agent_id = ?",
            (self.agent_id,)
        )

        # Activate new — register from builtin if needed
        persona = self.get(persona_id)
        if not persona:
            return False

        if persona_id in BUILTIN_PERSONAS:
            # Auto-register builtin to DB on first activation
            row = self.conn.execute(
                "SELECT id FROM personas WHERE id = ? AND agent_id = ?",
                (persona_id, self.agent_id)
            ).fetchone()
            if not row:
                self.register(persona_id, **{
                    k: v for k, v in BUILTIN_PERSONAS[persona_id].items()
                    if k != "name"
                }, name=BUILTIN_PERSONAS[persona_id]["name"])

        self.conn.execute(
            """UPDATE personas SET active = 1,
               usage_count = usage_count + 1, updated_at = ?
               WHERE id = ? AND agent_id = ?""",
            (_now(), persona_id, self.agent_id)
        )
        self.conn.commit()
        return True

    def active_persona(self) -> Optional[dict]:
        """Get the currently active persona."""
        row = self.conn.execute(
            "SELECT * FROM personas WHERE active = 1 AND agent_id = ?",
            (self.agent_id,)
        ).fetchone()
        if row:
            return self.get(row["id"])
        return None

    def deactivate(self) -> bool:
        """Deactivate the current persona."""
        self.conn.execute(
            "UPDATE personas SET active = 0 WHERE agent_id = ?",
            (self.agent_id,)
        )
        self.conn.commit()
        return True

    def list_personas(self, include_builtins: bool = True) -> list[dict]:
        """List all available personas."""
        personas = []

        # Custom personas from DB
        rows = self.conn.execute(
            """SELECT id, name, description, active, usage_count,
               effectiveness_score FROM personas WHERE agent_id = ?
               ORDER BY usage_count DESC""",
            (self.agent_id,)
        ).fetchall()

        seen_ids = set()
        for r in rows:
            seen_ids.add(r["id"])
            personas.append({
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "active": bool(r["active"]),
                "usage_count": r["usage_count"],
                "effectiveness_score": r["effectiveness_score"],
                "source": "custom",
            })

        # Add builtins not already registered
        if include_builtins:
            for pid, p in BUILTIN_PERSONAS.items():
                if pid not in seen_ids:
                    personas.append({
                        "id": pid,
                        "name": p["name"],
                        "description": p["description"],
                        "active": False,
                        "usage_count": 0,
                        "effectiveness_score": 0.5,
                        "source": "builtin",
                    })

        return personas

    def compose(self, persona_ids: list[str], name: str = "composed",
                resolution: str = "last_wins") -> dict:
        """
        Compose multiple personas into one. Useful for tasks that
        need traits from multiple roles (e.g., engineer + security).

        Resolution strategies for trait conflicts:
        - 'last_wins': Later personas override earlier ones
        - 'union': Combine all traits, rules, preferences
        - 'intersection': Only keep shared traits
        """
        merged = {
            "id": f"composed_{name}",
            "name": name,
            "description": f"Composed from: {', '.join(persona_ids)}",
            "traits": [],
            "communication_style": "",
            "system_prompt_prefix": "",
            "rules": [],
            "tools_preference": [],
            "parent_persona": None,
            "active": False,
            "usage_count": 0,
            "effectiveness_score": 0.5,
            "metadata": {"composed_from": persona_ids},
        }

        all_traits = []
        all_rules = []
        all_tools = []
        styles = []
        prefixes = []

        for pid in persona_ids:
            p = self.get(pid)
            if not p:
                continue
            all_traits.append(set(p.get("traits", [])))
            all_rules.extend(p.get("rules", []))
            all_tools.extend(p.get("tools_preference", []))
            if p.get("communication_style"):
                styles.append(p["communication_style"])
            if p.get("system_prompt_prefix"):
                prefixes.append(p["system_prompt_prefix"])

        if resolution == "union":
            merged["traits"] = list(set().union(*all_traits)) if all_traits else []
        elif resolution == "intersection":
            if all_traits:
                merged["traits"] = list(set.intersection(*all_traits))
            else:
                merged["traits"] = []
        else:  # last_wins for non-set fields
            merged["traits"] = list(set().union(*all_traits)) if all_traits else []

        # Deduplicate rules while preserving order
        seen_rules = set()
        deduped_rules = []
        for r in all_rules:
            if r not in seen_rules:
                seen_rules.add(r)
                deduped_rules.append(r)
        merged["rules"] = deduped_rules

        # Deduplicate tools
        seen_tools = set()
        deduped_tools = []
        for t in all_tools:
            if t not in seen_tools:
                seen_tools.add(t)
                deduped_tools.append(t)
        merged["tools_preference"] = deduped_tools

        merged["communication_style"] = " + ".join(styles) if styles else ""
        merged["system_prompt_prefix"] = " ".join(prefixes) if prefixes else ""

        return merged

    def generate_system_prompt(self, persona_id: Optional[str] = None,
                                context: str = "",
                                include_rules: bool = True) -> str:
        """
        Generate a complete system prompt from a persona.
        This is the main output — what gets injected into the LLM.
        """
        if persona_id:
            persona = self.get(persona_id)
        else:
            persona = self.active_persona()

        if not persona:
            return ""

        parts = []

        # Core identity
        if persona.get("system_prompt_prefix"):
            parts.append(persona["system_prompt_prefix"])

        # Description
        if persona.get("description"):
            parts.append(f"\n{persona['description']}")

        # Communication style
        if persona.get("communication_style"):
            parts.append(f"\nCommunication style: {persona['communication_style']}")

        # Traits
        if persona.get("traits"):
            traits_str = ", ".join(persona["traits"])
            parts.append(f"\nCore traits: {traits_str}")

        # Rules
        if include_rules and persona.get("rules"):
            parts.append("\nRules:")
            for i, rule in enumerate(persona["rules"], 1):
                parts.append(f"  {i}. {rule}")

        # Context injection
        if context:
            parts.append(f"\nCurrent context: {context}")

        return "\n".join(parts)

    def record_effectiveness(self, persona_id: str, score: float):
        """
        Update persona effectiveness based on task outcome.
        score: 0.0 (failed) to 1.0 (perfect).
        Uses exponential moving average.
        """
        row = self.conn.execute(
            "SELECT effectiveness_score FROM personas WHERE id = ? AND agent_id = ?",
            (persona_id, self.agent_id)
        ).fetchone()

        if row:
            alpha = 0.3  # Weight new observations more heavily
            new_score = alpha * score + (1 - alpha) * row["effectiveness_score"]
            self.conn.execute(
                """UPDATE personas SET effectiveness_score = ?,
                   updated_at = ? WHERE id = ? AND agent_id = ?""",
                (round(new_score, 4), _now(), persona_id, self.agent_id)
            )
            self.conn.commit()

    def recommend(self, task_description: str) -> list[dict]:
        """
        Recommend personas for a given task based on keyword matching
        and past effectiveness.
        """
        task_lower = task_description.lower()
        scored = []

        for persona in self.list_personas():
            pid = persona["id"]
            full = self.get(pid)
            if not full:
                continue

            score = 0.0

            # Keyword match against description + traits
            desc = (full.get("description", "") + " " +
                    " ".join(full.get("traits", []))).lower()
            words = set(task_lower.split())
            desc_words = set(desc.split())
            overlap = words & desc_words
            score += len(overlap) * 0.2

            # Effectiveness boost
            score += full.get("effectiveness_score", 0.5) * 0.3

            # Usage frequency bonus (proven personas)
            usage = full.get("usage_count", 0)
            score += min(usage * 0.05, 0.3)

            if score > 0.1:
                scored.append({
                    "persona_id": pid,
                    "name": full["name"],
                    "score": round(score, 3),
                    "reason": f"Matched on: {', '.join(overlap) if overlap else 'effectiveness'}"
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:5]

    def delete(self, persona_id: str) -> bool:
        """Delete a custom persona. Cannot delete builtins."""
        result = self.conn.execute(
            "DELETE FROM personas WHERE id = ? AND agent_id = ?",
            (persona_id, self.agent_id)
        )
        self.conn.commit()
        return result.rowcount > 0

    def stats(self) -> dict:
        """Persona system statistics."""
        custom_count = self.conn.execute(
            "SELECT COUNT(*) as c FROM personas WHERE agent_id = ?",
            (self.agent_id,)
        ).fetchone()["c"]

        active = self.active_persona()

        most_used = self.conn.execute(
            """SELECT id, name, usage_count FROM personas
               WHERE agent_id = ? ORDER BY usage_count DESC LIMIT 3""",
            (self.agent_id,)
        ).fetchall()

        return {
            "custom_personas": custom_count,
            "builtin_personas": len(BUILTIN_PERSONAS),
            "total_available": custom_count + len(BUILTIN_PERSONAS),
            "active_persona": active["name"] if active else None,
            "most_used": [{"id": r["id"], "name": r["name"],
                           "count": r["usage_count"]} for r in most_used],
        }
