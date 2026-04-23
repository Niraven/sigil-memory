"""
Sigil — Unified API.
One class, one file, all capabilities.
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional

from sigil.memory.engine import MemoryEngine, MemoryResult
from sigil.graph.knowledge import KnowledgeGraph, Triple, Entity
from sigil.activation.pka import ProactiveActivation
from sigil.orchestration.swarm import SwarmOrchestrator, SwarmResult
from sigil.bridge.a2a import A2ABridge, Event
from sigil.project.manager import ProjectManager, Project, ProjectTask
from sigil.compression.aaak import AAKCompressor
from sigil.memory.consolidation import MemoryConsolidator
from sigil.memory.entity_linking import EntityLinker
from sigil.orchestration.selfheal import SelfHealEngine
from sigil.persona.soul import PersonaManager, BUILTIN_PERSONAS


class Sigil:
    """
    The cognitive backbone for multi-agent AI systems.

    Usage:
        cx = Sigil("~/.sigil/brain.db", agent_id="zo")

        # Memory
        cx.remember("User prefers dark mode", type="semantic", importance=0.9)
        results = cx.recall("interface preferences", top_k=5)

        # Knowledge graph
        cx.graph.add("niam", "works_on", "zo.space")
        cx.graph.query(subject="niam")

        # Proactive activation
        brief = cx.activate(persona="engineer")

        # Orchestration
        result = cx.orchestrate([
            {"id": "research", "prompt": "Find best practices"},
            {"id": "implement", "prompt": "Build it", "depends_on": ["research"]},
        ])

        # Multi-agent sync
        cx.sync.emit("decision_made", {"what": "use postgres"})
        events = cx.sync.pull()

        # Project management
        pid = cx.project.create("auth-migration")
        cx.project.add_task(pid, "Implement JWT refresh")
    """

    def __init__(self, db_path: str = "~/.sigil/brain.db",
                 agent_id: str = "default",
                 event_file: Optional[str] = None,
                 wm_ttl_hours: int = 24,
                 wm_max_items: int = 10000,
                 recency_halflife_hours: float = 168.0,
                 max_concurrent: int = 8,
                 budget_limit: float = 10.0):
        """
        Initialize Sigil.

        Args:
            db_path: Path to SQLite database file
            agent_id: Identifier for this agent (e.g., 'zo', 'hermes')
            event_file: Optional path to JSONL event file for cross-process sync
            wm_ttl_hours: Working memory TTL in hours
            wm_max_items: Max working memory items
            recency_halflife_hours: Half-life for recency decay in retrieval
            max_concurrent: Max concurrent tasks in swarm
            budget_limit: Budget limit for swarm orchestration
        """
        # Core memory engine
        self.memory = MemoryEngine(
            db_path=db_path,
            agent_id=agent_id,
            wm_ttl_hours=wm_ttl_hours,
            wm_max_items=wm_max_items,
            recency_halflife_hours=recency_halflife_hours
        )

        # Knowledge graph (shares connection)
        self.graph = KnowledgeGraph(
            conn=self.memory._get_conn(),
            agent_id=agent_id
        )

        # Proactive activation
        self._pka = ProactiveActivation(
            memory_engine=self.memory,
            knowledge_graph=self.graph
        )

        # Swarm orchestrator
        self.swarm = SwarmOrchestrator(
            memory_engine=self.memory,
            max_concurrent=max_concurrent,
            budget_limit=budget_limit
        )

        # A2A bridge
        self.sync = A2ABridge(
            conn=self.memory._get_conn(),
            agent_id=agent_id,
            event_file=event_file
        )

        # Project manager
        self.project = ProjectManager(
            conn=self.memory._get_conn(),
            agent_id=agent_id
        )

        # Compression
        self.compressor = AAKCompressor()

        # v2: Consolidation (sleep, reflection, surprise detection)
        self.consolidator = MemoryConsolidator(
            conn=self.memory._get_conn(),
            agent_id=agent_id
        )

        # v2: Entity linking (Mem0-inspired multi-signal retrieval)
        self.entities = EntityLinker(
            conn=self.memory._get_conn(),
            agent_id=agent_id
        )

        # v2: Self-healing (stagnation detection, capability gap tracking)
        self.health = SelfHealEngine(
            conn=self.memory._get_conn(),
            agent_id=agent_id
        )

        # v3: Persona system (SOUL registry)
        self.persona = PersonaManager(
            conn=self.memory._get_conn(),
            agent_id=agent_id
        )

        # Config
        self.agent_id = agent_id
        self.db_path = db_path

    # ── Memory Shortcuts ──────────────────────────────────────────

    def remember(self, content: str, type: str = "semantic", **kwargs) -> str:
        """Store a memory. Types: semantic, episodic, procedural, working."""
        mid = self.memory.remember(content, type=type, **kwargs)

        # v2: Auto-link entities from content
        if type in ("semantic", "episodic"):
            self.entities.link_memory(mid, type, content)

        # Emit sync event
        self.sync.emit("memory_created", {
            "content": content[:200],
            "type": type,
        }, memory_id=mid, memory_table=type)

        return mid

    def recall(self, query: str, top_k: int = 5, **kwargs) -> list[MemoryResult]:
        """
        Hybrid recall with 5-signal fusion:
        1. Vector similarity (50%)
        2. FTS5 keyword match (30%)
        3. Importance + recency (20%)
        4. Knowledge graph boost (bonus)
        5. Entity linking boost (bonus, v2)
        """
        results = self.memory.recall(query, top_k=top_k * 2, **kwargs)

        # Apply graph boost + entity boost (v2)
        for result in results:
            graph_boost = self.graph.boost_score(result.content, query)
            entity_boost = self.entities.entity_boost(query, result.content)
            result.score = min(1.0, result.score + graph_boost + entity_boost)

        # Re-sort after boosts and trim to top_k
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def recall_compressed(self, query: str, top_k: int = 5,
                          max_tokens: int = 2000) -> str:
        """Recall and compress for LLM injection."""
        results = self.recall(query, top_k=top_k)
        memories = [r.to_dict() for r in results]
        return self.compressor.compress_memories(memories, max_tokens=max_tokens)

    # ── Knowledge Graph Shortcuts ─────────────────────────────────

    def learn(self, subject: str, predicate: str, obj: str,
              confidence: float = 1.0, **kwargs) -> str:
        """Add a fact to the knowledge graph."""
        tid = self.graph.add(subject, predicate, obj, confidence=confidence, **kwargs)
        self.sync.emit("triple_created", {
            "subject": subject, "predicate": predicate, "object": obj
        })
        return tid

    def about(self, entity: str) -> Entity:
        """Get everything known about an entity."""
        return self.graph.entity(entity)

    # ── Activation ────────────────────────────────────────────────

    def activate(self, persona: str = "default",
                 session_context: str = "",
                 active_projects: Optional[list[str]] = None) -> dict:
        """Generate a proactive activation briefing."""
        return self._pka.activate(
            persona=persona,
            session_context=session_context,
            active_projects=active_projects
        )

    def activation_prompt(self, **kwargs) -> str:
        """Generate activation briefing as injectable prompt text."""
        brief = self.activate(**kwargs)
        return self._pka.to_prompt(brief)

    # ── Orchestration ─────────────────────────────────────────────

    def orchestrate(self, tasks: list[dict], **kwargs) -> SwarmResult:
        """Execute a DAG of tasks via the swarm orchestrator."""
        return self.swarm.orchestrate(tasks, **kwargs)

    # ── v2: Consolidation ──────────────────────────────────────────

    def sleep(self, max_age_hours: int = 24) -> dict:
        """Consolidate old working memory into episodic summaries."""
        return self.consolidator.sleep(max_age_hours=max_age_hours)

    def check_health(self, output: str = "", progress: float = -1,
                     error: str = "", context: str = "") -> dict:
        """Run self-healing checks (stagnation, capability gaps)."""
        return self.health.check(output=output, progress=progress,
                                 error=error, context=context)

    def health_report(self) -> dict:
        """Get full self-healing report."""
        return self.health.report()

    # ── v3: Persona / SOUL ─────────────────────────────────────────

    def set_persona(self, persona_id: str) -> bool:
        """Activate a persona for this agent."""
        return self.persona.activate(persona_id)

    def system_prompt(self, persona_id: Optional[str] = None,
                      context: str = "",
                      include_activation: bool = True) -> str:
        """
        Generate a complete system prompt combining persona + activation.
        This is the main output for LLM injection.
        """
        parts = []

        # Persona prompt
        persona_prompt = self.persona.generate_system_prompt(
            persona_id=persona_id, context=context
        )
        if persona_prompt:
            parts.append(persona_prompt)

        # Activation brief
        if include_activation:
            brief = self.activate(
                persona=persona_id or "default",
                session_context=context
            )
            activation_text = self.activation_prompt(
                persona=persona_id or "default",
                session_context=context
            )
            if activation_text and len(activation_text) > 50:
                parts.append("\n" + activation_text)

        return "\n\n".join(parts) if parts else ""

    # ── Stats ─────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Full system statistics."""
        return {
            "memory": self.memory.stats(),
            "graph": self.graph.stats(),
            "bridge": self.sync.stats(),
            "orchestrator": self.swarm.stats(),
            "entity_links": self.entities.stats(),
            "health": self.health.report(),
            "persona": self.persona.stats(),
            "agent_id": self.agent_id,
            "db_path": str(self.db_path),
        }

    # ── Export / Import ───────────────────────────────────────────

    def export_json(self, path: str):
        """Export entire Sigil state to JSON."""
        self.memory.export_json(path)

    def import_json(self, path: str):
        """Import Sigil state from JSON."""
        self.memory.import_json(path)

    # ── Lifecycle ─────────────────────────────────────────────────

    def close(self):
        """Close the database connection."""
        self.memory.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self):
        return f"Sigil(agent='{self.agent_id}', db='{self.db_path}')"
