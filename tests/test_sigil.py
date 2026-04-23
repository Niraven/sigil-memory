"""
Comprehensive tests for Sigil.
Tests memory engine, knowledge graph, PKA, orchestration, A2A bridge,
projects, personas, consolidation, entity linking, and self-healing.
100+ tests covering all modules.
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta

import pytest

# Add parent to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sigil.core import Sigil
from sigil.memory.engine import MemoryEngine
from sigil.memory.embeddings import has_embeddings
from sigil.memory.entity_linking import EntityLinker, ENTITY_PATTERNS, STOP_ENTITIES
from sigil.memory.consolidation import MemoryConsolidator
from sigil.graph.knowledge import KnowledgeGraph
from sigil.orchestration.swarm import ComplexityEstimator, ModelTier, SwarmOrchestrator
from sigil.orchestration.selfheal import StagnationDetector, CapabilityTracker, SelfHealEngine
from sigil.compression.aaak import AAKCompressor
from sigil.persona.soul import PersonaManager, BUILTIN_PERSONAS
from sigil.bridge.a2a import A2ABridge, Event
from sigil.project.manager import ProjectManager


@pytest.fixture
def tmp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def sigil(tmp_db):
    """Create a Sigil instance for testing."""
    cx = Sigil(db_path=tmp_db, agent_id="test")
    yield cx
    cx.close()


# ── Memory Engine Tests ───────────────────────────────────────────

class TestMemoryEngine:

    def test_remember_semantic(self, sigil):
        mid = sigil.remember("Python is a programming language", type="semantic",
                              category="tech", importance=0.8)
        assert mid.startswith("sem_")

        mem = sigil.memory.get(mid)
        assert mem is not None
        assert mem["content"] == "Python is a programming language"
        assert mem["importance"] == 0.8

    def test_remember_episodic(self, sigil):
        mid = sigil.remember("Deployed auth service successfully",
                              type="episodic", summary="Deployed auth service successfully",
                              outcome="success", importance=0.7)
        assert mid.startswith("epi_")

    def test_remember_procedural(self, sigil):
        mid = sigil.remember("Deploy flow", type="procedural",
                              name="deploy", steps=["build", "test", "push"])
        assert mid.startswith("proc_")

    def test_remember_working(self, sigil):
        mid = sigil.remember("Current task: fix auth bug", type="working",
                              importance=0.9)
        assert mid.startswith("wm_")

    def test_recall_fts(self, sigil):
        sigil.remember("Python is great for data science", type="semantic",
                        category="tech")
        sigil.remember("JavaScript runs in the browser", type="semantic",
                        category="tech")
        sigil.remember("Deployed the Python microservice", type="episodic",
                        summary="Deployed the Python microservice")

        results = sigil.recall("Python", top_k=5)
        assert len(results) > 0
        # Python-related memories should rank higher
        assert any("Python" in r.content for r in results)

    def test_recall_empty(self, sigil):
        results = sigil.recall("nonexistent topic")
        assert results == []

    def test_delete_memory(self, sigil):
        mid = sigil.remember("Temporary fact", type="semantic")
        assert sigil.memory.get(mid) is not None
        sigil.memory.delete(mid)
        assert sigil.memory.get(mid) is None

    def test_memory_count(self, sigil):
        sigil.remember("Fact 1", type="semantic")
        sigil.remember("Fact 2", type="semantic")
        sigil.remember("Event 1", type="episodic",
                        summary="Event 1")

        counts = sigil.memory.count()
        assert counts["semantic"] == 2
        assert counts["episodic"] == 1

    def test_memory_stats(self, sigil):
        sigil.remember("Test fact", type="semantic")
        stats = sigil.memory.stats()
        assert stats["memories"]["semantic"] >= 1
        assert stats["db_size_bytes"] > 0
        assert "agent_id" in stats

    def test_working_memory_ttl(self, sigil):
        # Manually insert an already-expired working memory
        from datetime import datetime, timezone
        conn = sigil.memory._get_conn()
        conn.execute(
            """INSERT INTO working (id, content, importance, session_id, agent_id,
               created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("wm_expired", "Ephemeral", 0.5, "", "test",
             "2020-01-01T00:00:00.000000", "2020-01-01T00:00:01.000000")
        )
        conn.commit()
        sigil.memory._evict_working()
        mem = sigil.memory.get("wm_expired")
        assert mem is None

    def test_evolve_procedure(self, sigil):
        mid = sigil.memory.remember_procedural(
            "deploy", ["build", "push", "verify"])
        success = sigil.memory.evolve_procedure(
            mid, failed_at_step=1, failure_context="Push failed due to auth")
        assert success

        mem = sigil.memory.get(mid)
        steps = json.loads(mem["steps"])
        assert len(steps) == 4  # Original 3 + 1 auto-fix
        assert mem["version"] == 2
        assert mem["failure_count"] == 1

    def test_export_import(self, sigil, tmp_db):
        sigil.remember("Export test fact", type="semantic")
        sigil.learn("niam", "uses", "sigil")

        export_path = tmp_db + ".export.json"
        sigil.export_json(export_path)

        assert os.path.exists(export_path)
        with open(export_path) as f:
            data = json.load(f)
        assert len(data["semantic"]) >= 1
        assert len(data["triples"]) >= 1

        # Import into a new instance
        fd, new_db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            cx2 = Sigil(db_path=new_db, agent_id="test")
            cx2.import_json(export_path)
            assert cx2.memory.count()["semantic"] >= 1
            cx2.close()
        finally:
            os.unlink(new_db)
            os.unlink(export_path)


# ── Knowledge Graph Tests ─────────────────────────────────────────

class TestKnowledgeGraph:

    def test_add_triple(self, sigil):
        tid = sigil.learn("niam", "works_on", "zo.space")
        assert tid.startswith("triple_")

    def test_query_triples(self, sigil):
        sigil.learn("niam", "works_on", "zo.space")
        sigil.learn("niam", "uses", "python")
        sigil.learn("hermes", "runs_on", "desktop")

        results = sigil.graph.query(subject="niam")
        assert len(results) == 2

    def test_temporal_validity(self, sigil):
        sigil.learn("niam", "works_at", "company_a",
                     valid_from="2024-01-01T00:00:00.000000",
                     valid_until="2025-01-01T00:00:00.000000")
        sigil.learn("niam", "works_at", "company_b",
                     valid_from="2025-01-01T00:00:00.000000")

        # Query as of mid-2024
        results = sigil.graph.query(subject="niam", predicate="works_at",
                                     as_of="2024-06-01T00:00:00.000000")
        assert len(results) == 1
        assert results[0].object == "company_a"

        # Query as of mid-2025
        results = sigil.graph.query(subject="niam", predicate="works_at",
                                     as_of="2025-06-01T00:00:00.000000")
        assert len(results) == 1
        assert results[0].object == "company_b"

    def test_auto_invalidation(self, sigil):
        sigil.learn("niam", "works_at", "old_company")
        sigil.learn("niam", "works_at", "new_company")

        results = sigil.graph.query(subject="niam", predicate="works_at")
        assert len(results) == 1
        assert results[0].object == "new_company"

    def test_entity_profile(self, sigil):
        sigil.learn("niam", "works_on", "zo.space")
        sigil.learn("niam", "uses", "python")
        sigil.learn("zo.space", "built_with", "react")

        entity = sigil.about("niam")
        assert entity.name == "niam"
        assert entity.out_degree == 2

    def test_graph_search(self, sigil):
        sigil.learn("niam", "expert_in", "AI systems")
        sigil.learn("niam", "builds", "memory engines")

        results = sigil.graph.search("AI")
        assert len(results) > 0

    def test_invalidate(self, sigil):
        tid = sigil.learn("niam", "status_is", "busy")
        assert sigil.graph.invalidate(tid)

        # Should not appear in active queries
        results = sigil.graph.query(subject="niam", predicate="status_is")
        assert len(results) == 0

    def test_graph_stats(self, sigil):
        sigil.learn("a", "relates_to", "b")
        sigil.learn("b", "relates_to", "c")
        stats = sigil.graph.stats()
        assert stats["active_triples"] == 2
        assert stats["unique_entities"] >= 2


# ── A2A Bridge Tests ──────────────────────────────────────────────

class TestA2ABridge:

    def test_emit_event(self, sigil):
        eid = sigil.sync.emit("decision_made", {"what": "use postgres"})
        assert eid.startswith("evt_")

    def test_pull_events(self, tmp_db):
        # Create two agents sharing the same DB
        cx1 = Sigil(db_path=tmp_db, agent_id="zo")
        cx2 = Sigil(db_path=tmp_db, agent_id="hermes")

        cx1.sync.emit("decision", {"content": "Use SQLite"})
        events = cx2.sync.pull()
        assert len(events) == 1
        assert events[0].payload["content"] == "Use SQLite"

        # Pulling again should return nothing (already synced)
        events = cx2.sync.pull()
        assert len(events) == 0

        cx1.close()
        cx2.close()

    def test_event_handlers(self, sigil):
        received = []
        sigil.sync.on("test_event", lambda e: received.append(e))
        sigil.sync.emit("test_event", {"data": "hello"})
        assert len(received) == 1
        assert received[0].payload["data"] == "hello"

    def test_event_file_sync(self, tmp_db):
        fd, event_file = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            cx1 = Sigil(db_path=tmp_db, agent_id="zo", event_file=event_file)
            cx2 = Sigil(db_path=tmp_db + ".2", agent_id="hermes",
                         event_file=event_file)

            cx1.sync.emit("shared_event", {"data": "cross-process"})
            events = cx2.sync.pull_from_file()
            assert len(events) == 1
            assert events[0].payload["data"] == "cross-process"

            cx1.close()
            cx2.close()
        finally:
            os.unlink(event_file)
            if os.path.exists(tmp_db + ".2"):
                os.unlink(tmp_db + ".2")

    def test_recent_events(self, sigil):
        sigil.sync.emit("event_a", {"n": 1})
        sigil.sync.emit("event_b", {"n": 2})
        sigil.sync.emit("event_a", {"n": 3})

        all_events = sigil.sync.recent(limit=10)
        assert len(all_events) == 3

        type_a = sigil.sync.recent(limit=10, event_type="event_a")
        assert len(type_a) == 2


# ── Project Manager Tests ─────────────────────────────────────────

class TestProjectManager:

    def test_create_project(self, sigil):
        pid = sigil.project.create("auth-migration",
                                    description="Migrate to JWT",
                                    milestone="v1.0")
        assert pid.startswith("proj_")

    def test_add_tasks(self, sigil):
        pid = sigil.project.create("test-project")
        t1 = sigil.project.add_task(pid, "Design schema", priority="high")
        t2 = sigil.project.add_task(pid, "Implement API",
                                     depends_on=[t1], assignee="hermes")
        t3 = sigil.project.add_task(pid, "Write tests",
                                     depends_on=[t2])

        tasks = sigil.project.list_tasks(pid)
        assert len(tasks) == 3

    def test_project_status(self, sigil):
        pid = sigil.project.create("status-test")
        t1 = sigil.project.add_task(pid, "Task 1", priority="high")
        t2 = sigil.project.add_task(pid, "Task 2", depends_on=[t1])
        sigil.project.add_task(pid, "Task 3")

        sigil.project.update_task(t1, status="completed")

        status = sigil.project.status(pid)
        assert status["progress"] > 0
        assert status["total_tasks"] == 3
        assert len(status["next_actions"]) > 0

    def test_active_work(self, sigil):
        pid = sigil.project.create("work-test")
        tid = sigil.project.add_task(pid, "Active task")
        sigil.project.update_task(tid, status="in_progress")

        work = sigil.project.active_work()
        assert len(work) == 1
        assert work[0]["task"] == "Active task"

    def test_blockers(self, sigil):
        pid = sigil.project.create("blocker-test")
        t1 = sigil.project.add_task(pid, "Blocking task")
        t2 = sigil.project.add_task(pid, "Blocked task", depends_on=[t1])

        status = sigil.project.status(pid)
        assert len(status["blockers"]) == 1


# ── Orchestration Tests ───────────────────────────────────────────

class TestOrchestration:

    def test_complexity_estimator(self):
        estimator = ComplexityEstimator()

        tier, score = estimator.estimate("list all files")
        assert tier == ModelTier.LIGHT

        tier, score = estimator.estimate(
            "Architect a microservice system with OAuth2, JWT authentication, "
            "PostgreSQL database with pgvector for semantic search, "
            "implement comprehensive API endpoints with rate limiting, "
            "then deploy to Kubernetes with CI/CD pipeline"
        )
        assert tier in (ModelTier.MID, ModelTier.HEAVY)

    def test_orchestrate_simple(self, sigil):
        # Register a mock executor
        def mock_executor(prompt, tier):
            return f"Result for: {prompt[:50]}"

        sigil.swarm.register_executor("default", mock_executor)

        result = sigil.orchestrate([
            {"id": "task1", "prompt": "Do something"},
            {"id": "task2", "prompt": "Do another thing", "depends_on": ["task1"]},
        ])
        assert result.success_count == 2
        assert result.failure_count == 0

    def test_orchestrate_with_failure(self, sigil):
        call_count = [0]

        def flaky_executor(prompt, tier):
            call_count[0] += 1
            if "fail" in prompt.lower():
                raise Exception("Simulated failure")
            return "OK"

        sigil.swarm.register_executor("default", flaky_executor)

        result = sigil.orchestrate([
            {"id": "good", "prompt": "Do good work"},
            {"id": "bad", "prompt": "Please fail now"},
            {"id": "dependent", "prompt": "Need bad result", "depends_on": ["bad"]},
        ])
        assert result.success_count == 1
        assert result.failure_count == 1
        assert result.skipped_count == 1

    def test_cycle_detection(self, sigil):
        def mock(prompt, tier):
            return "ok"
        sigil.swarm.register_executor("default", mock)

        with pytest.raises(ValueError, match="cycle"):
            sigil.orchestrate([
                {"id": "a", "prompt": "A", "depends_on": ["b"]},
                {"id": "b", "prompt": "B", "depends_on": ["a"]},
            ])


# ── Compression Tests ─────────────────────────────────────────────

class TestCompression:

    def test_verbose_replacement(self):
        comp = AAKCompressor()
        result = comp.compress("In order to fix the bug due to the fact that it was broken")
        assert "to fix" in result
        assert "because" in result

    def test_compress_memories(self):
        comp = AAKCompressor()
        memories = [
            {"content": "User basically essentially prefers dark mode", "table": "semantic",
             "score": 0.9},
            {"content": "Deployed service in order to fix the auth issue", "table": "episodic",
             "score": 0.7},
        ]
        result = comp.compress_memories(memories, max_tokens=500)
        assert "[F]" in result
        assert "[E]" in result

    def test_dedup_sentences(self):
        comp = AAKCompressor()
        result = comp.compress("The system works. The system works. It also does X.")
        assert result.count("system works") == 1

    def test_compression_stats(self):
        comp = AAKCompressor()
        original = "In order to fix the bug due to the fact that it was broken at this point in time"
        compressed = comp.compress(original)
        stats = comp.stats(original, compressed)
        assert stats["reduction_pct"] > 0
        assert stats["compressed_chars"] < stats["original_chars"]


# ── Proactive Activation Tests ────────────────────────────────────

class TestPKA:

    def test_activate_empty(self, sigil):
        brief = sigil.activate()
        assert "generated_at" in brief
        assert "summary" in brief

    def test_activate_with_data(self, sigil):
        sigil.remember("Auth migration in progress", type="episodic",
                        summary="Auth migration in progress",
                        outcome="pending", importance=0.8)
        sigil.remember("Niam prefers TypeScript", type="semantic",
                        importance=0.7)

        pid = sigil.project.create("auth")
        sigil.project.add_task(pid, "Fix JWT refresh", priority="high")

        brief = sigil.activate(session_context="authentication",
                                active_projects=["auth"])
        assert len(brief["sections"]) > 0

    def test_activation_prompt(self, sigil):
        sigil.remember("Important decision", type="episodic",
                        summary="Important decision", outcome="pending")
        prompt = sigil.activation_prompt()
        assert "[SIGIL ACTIVATION BRIEF]" in prompt


# ── Full System Stats Test ────────────────────────────────────────

class TestSystem:

    def test_full_stats(self, sigil):
        sigil.remember("Test", type="semantic")
        sigil.learn("a", "b", "c")
        sigil.sync.emit("test", {})

        stats = sigil.stats()
        assert "memory" in stats
        assert "graph" in stats
        assert "bridge" in stats
        assert "orchestrator" in stats

    def test_context_manager(self, tmp_db):
        with Sigil(db_path=tmp_db, agent_id="ctx_test") as cx:
            cx.remember("Context manager test", type="semantic")
            assert cx.memory.count()["semantic"] == 1


# ── v2: Consolidation Tests ──────────────────────────────────────

class TestConsolidation:

    def test_sleep_empty(self, sigil):
        result = sigil.sleep(max_age_hours=0)
        assert result["consolidated"] == 0

    def test_sleep_consolidates(self, sigil):
        # Add old working memory by backdating
        conn = sigil.memory._get_conn()
        for i in range(5):
            conn.execute(
                """INSERT INTO working (id, content, importance, session_id,
                   agent_id, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (f"wm_old_{i}", f"Old context {i}", 0.5, "session_1", "test",
                 "2020-01-01T00:00:00.000000", "2020-01-02T00:00:00.000000")
            )
        conn.commit()

        result = sigil.sleep(max_age_hours=1)
        assert result["removed"] == 5
        assert result["consolidated"] >= 1
        # Working memories should be gone
        count = conn.execute("SELECT COUNT(*) as c FROM working WHERE id LIKE 'wm_old_%'").fetchone()["c"]
        assert count == 0
        # Episodic should have the consolidated entry
        assert sigil.memory.count()["episodic"] >= 1

    def test_contradiction_detection(self, sigil):
        sigil.learn("niam", "works_at", "company_x")
        # Content must contain both the subject and predicate (with space instead of _)
        # but reference a different object
        sigil.remember("niam works at company_y now", type="semantic")
        contradictions = sigil.consolidator.detect_contradictions()
        assert len(contradictions) >= 1

    def test_decay_audit(self, sigil):
        sigil.remember("Low importance", type="semantic", importance=0.1)
        sigil.remember("High importance", type="semantic", importance=0.9)
        audit = sigil.consolidator.decay_audit()
        assert "standard" in audit


# ── v2: Entity Linking Tests ─────────────────────────────────────

class TestEntityLinking:

    def test_extract_entities(self, sigil):
        entities = sigil.entities.extract_entities(
            "Niam uses Python and TypeScript on GitHub")
        names = {e["value"] for e in entities}
        assert "Python" in names
        assert "TypeScript" in names
        assert "GitHub" in names

    def test_auto_linking_on_remember(self, sigil):
        sigil.remember("Niam deployed the Python service to Docker", type="semantic")
        stats = sigil.entities.stats()
        assert stats["mention_links"] > 0

    def test_entity_boost(self, sigil):
        sigil.remember("Python is great for data science", type="semantic")
        sigil.remember("JavaScript runs in the browser", type="semantic")
        # Entity boost should favor Python result when querying about Python
        boost = sigil.entities.entity_boost("Python programming", "Python is great for data science")
        assert boost > 0


# ── v2: Self-Healing Tests ───────────────────────────────────────

class TestSelfHeal:

    def test_stagnation_detection(self, sigil):
        # Feed same output 3 times
        sigil.check_health(output="same output here")
        sigil.check_health(output="same output here")
        result = sigil.check_health(output="same output here")
        assert not result["healthy"]
        assert "repetitive_output" in result["issues"]

    def test_capability_gap_tracking(self, sigil):
        sigil.check_health(error="API timeout on Gmail", context="sending email")
        result = sigil.check_health(error="API timeout on Gmail", context="reading inbox")
        assert result["issues"]  # Should surface after 2nd occurrence
        assert any("recurring" in i for i in result["issues"])

    def test_capability_gap_resolve(self, sigil):
        sigil.health.capabilities.record_failure("test error")
        sigil.health.capabilities.record_failure("test error")
        gaps = sigil.health.capabilities.open_gaps()
        assert len(gaps) >= 1
        sigil.health.capabilities.resolve(gaps[0]["gap_id"], "Fixed by adding retry logic")
        gaps_after = sigil.health.capabilities.open_gaps()
        assert len(gaps_after) == 0

    def test_health_report(self, sigil):
        report = sigil.health_report()
        assert "capability_gaps" in report

    def test_progress_plateau(self, sigil):
        for _ in range(6):
            result = sigil.check_health(progress=0.5)
        assert not result["healthy"]
        assert "progress_plateau" in result["issues"]

    def test_stagnation_reset(self, sigil):
        """After reset, stagnation should not trigger for first occurrences."""
        sigil.check_health(output="repeated thing")
        sigil.check_health(output="repeated thing")
        sigil.health.stagnation.reset()
        # After reset, first occurrence shouldn't trigger
        result = sigil.check_health(output="fresh new output")
        assert result["healthy"]

    def test_empty_output_detection(self, sigil):
        result = sigil.check_health(output="   ")
        assert not result["healthy"]
        assert "empty_output" in result["issues"]

    def test_combined_health_check(self, sigil):
        """Multiple issues detected simultaneously."""
        sigil.check_health(output="repeat", progress=0.5)
        sigil.check_health(output="repeat", progress=0.5)
        sigil.check_health(output="repeat", progress=0.5)
        sigil.check_health(output="repeat", progress=0.5)
        result = sigil.check_health(output="repeat", progress=0.5,
                                     error="timeout", context="test")
        assert len(result["issues"]) >= 2

    def test_capability_weekly_report(self, sigil):
        sigil.health.capabilities.record_failure("auth error", "login flow")
        sigil.health.capabilities.record_failure("auth error", "signup flow")
        report = sigil.health.capabilities.weekly_report()
        assert report["new_gaps_this_week"] >= 1


# ── v3: Persona / SOUL Tests ────────────────────────────────────

class TestPersona:

    def test_builtin_personas_exist(self):
        assert len(BUILTIN_PERSONAS) >= 12
        assert "engineer" in BUILTIN_PERSONAS
        assert "researcher" in BUILTIN_PERSONAS
        assert "writer" in BUILTIN_PERSONAS

    def test_builtin_persona_structure(self):
        for pid, p in BUILTIN_PERSONAS.items():
            assert "name" in p
            assert "description" in p
            assert "traits" in p
            assert "rules" in p
            assert len(p["traits"]) > 0
            assert len(p["rules"]) > 0

    def test_get_builtin(self, sigil):
        p = sigil.persona.get("engineer")
        assert p is not None
        assert p["name"] == "Engineer"
        assert "precise" in p["traits"]

    def test_get_nonexistent(self, sigil):
        p = sigil.persona.get("nonexistent_persona_xyz")
        assert p is None

    def test_register_custom(self, sigil):
        pid = sigil.persona.register(
            "my_agent", "My Agent",
            description="Custom agent for testing",
            traits=["fast", "thorough"],
            rules=["Always verify results"],
        )
        assert pid == "my_agent"
        p = sigil.persona.get("my_agent")
        assert p["name"] == "My Agent"
        assert "fast" in p["traits"]

    def test_register_update(self, sigil):
        sigil.persona.register("updatable", "V1", traits=["old"])
        sigil.persona.register("updatable", "V2", traits=["new"])
        p = sigil.persona.get("updatable")
        assert p["name"] == "V2"
        assert "new" in p["traits"]

    def test_activate_persona(self, sigil):
        sigil.persona.register("test_p", "Test Persona",
                                traits=["test_trait"])
        assert sigil.persona.activate("test_p")
        active = sigil.persona.active_persona()
        assert active is not None
        assert active["id"] == "test_p"

    def test_activate_builtin(self, sigil):
        assert sigil.persona.activate("engineer")
        active = sigil.persona.active_persona()
        assert active["name"] == "Engineer"

    def test_deactivate(self, sigil):
        sigil.persona.activate("engineer")
        sigil.persona.deactivate()
        assert sigil.persona.active_persona() is None

    def test_activate_switches(self, sigil):
        """Activating a new persona deactivates the old one."""
        sigil.persona.activate("engineer")
        sigil.persona.activate("researcher")
        active = sigil.persona.active_persona()
        assert active["name"] == "Researcher"

    def test_list_personas(self, sigil):
        personas = sigil.persona.list_personas()
        assert len(personas) >= len(BUILTIN_PERSONAS)
        names = {p["name"] for p in personas}
        assert "Engineer" in names

    def test_list_custom_and_builtin(self, sigil):
        sigil.persona.register("custom1", "Custom One")
        personas = sigil.persona.list_personas()
        ids = {p["id"] for p in personas}
        assert "custom1" in ids
        assert "engineer" in ids

    def test_compose_union(self, sigil):
        composed = sigil.persona.compose(
            ["engineer", "security"], name="secure_engineer",
            resolution="union"
        )
        assert "precise" in composed["traits"]
        assert "paranoid" in composed["traits"]
        assert len(composed["rules"]) > 4  # Combined from both

    def test_compose_intersection(self, sigil):
        # Register two custom personas with overlapping traits
        sigil.persona.register("a", "A", traits=["careful", "thorough", "fast"])
        sigil.persona.register("b", "B", traits=["thorough", "precise", "fast"])
        composed = sigil.persona.compose(
            ["a", "b"], resolution="intersection"
        )
        assert "thorough" in composed["traits"]
        assert "fast" in composed["traits"]
        assert "careful" not in composed["traits"]

    def test_generate_system_prompt(self, sigil):
        prompt = sigil.persona.generate_system_prompt("engineer")
        assert "senior software engineer" in prompt
        assert "Rules:" in prompt

    def test_generate_prompt_with_context(self, sigil):
        prompt = sigil.persona.generate_system_prompt(
            "researcher", context="Analyzing memory systems"
        )
        assert "research" in prompt.lower()
        assert "memory systems" in prompt

    def test_record_effectiveness(self, sigil):
        sigil.persona.activate("engineer")
        sigil.persona.record_effectiveness("engineer", 0.9)
        p = sigil.persona.get("engineer")
        assert p["effectiveness_score"] != 0.5  # Should have changed

    def test_recommend_persona(self, sigil):
        sigil.persona.activate("engineer")
        sigil.persona.record_effectiveness("engineer", 0.95)
        recs = sigil.persona.recommend("Fix the Python code and run tests")
        assert len(recs) > 0

    def test_delete_custom(self, sigil):
        sigil.persona.register("to_delete", "Deletable")
        assert sigil.persona.delete("to_delete")
        assert sigil.persona.get("to_delete") is None  # Falls through to builtins check, returns None

    def test_parent_inheritance(self, sigil):
        sigil.persona.register("base_agent", "Base",
                                traits=["careful", "thorough"],
                                rules=["Always double-check"])
        sigil.persona.register("child_agent", "Child",
                                parent_persona="base_agent",
                                description="Specialized child")
        child = sigil.persona.get("child_agent")
        assert "careful" in child["traits"]
        assert "Always double-check" in child["rules"]

    def test_usage_count_increments(self, sigil):
        sigil.persona.activate("engineer")
        sigil.persona.activate("engineer")
        p = sigil.persona.get("engineer")
        assert p["usage_count"] >= 2

    def test_persona_stats(self, sigil):
        sigil.persona.activate("engineer")
        stats = sigil.persona.stats()
        assert stats["builtin_personas"] >= 12
        assert stats["active_persona"] == "Engineer"

    def test_sigil_set_persona(self, sigil):
        assert sigil.set_persona("writer")
        active = sigil.persona.active_persona()
        assert active["name"] == "Writer"

    def test_sigil_system_prompt(self, sigil):
        sigil.set_persona("engineer")
        prompt = sigil.system_prompt()
        assert "senior software engineer" in prompt


# ── Extended Memory Engine Tests ─────────────────────────────────

class TestMemoryEngineExtended:

    def test_remember_with_metadata(self, sigil):
        mid = sigil.remember("Tagged fact", type="semantic",
                              metadata={"tags": ["important", "tech"]})
        mem = sigil.memory.get(mid)
        meta = json.loads(mem["metadata"])
        assert "important" in meta["tags"]

    def test_remember_with_category(self, sigil):
        mid = sigil.remember("Categorized fact", type="semantic",
                              category="tech")
        mem = sigil.memory.get(mid)
        assert mem["category"] == "tech"

    def test_remember_with_source(self, sigil):
        mid = sigil.remember("Sourced fact", type="semantic",
                              source="unit_test")
        mem = sigil.memory.get(mid)
        assert mem["source"] == "unit_test"

    def test_multiple_working_memories(self, sigil):
        for i in range(5):
            sigil.remember(f"Working item {i}", type="working")
        count = sigil.memory.count()
        assert count["working"] == 5

    def test_episodic_with_outcome(self, sigil):
        mid = sigil.remember("Deployment", type="episodic",
                              summary="Deployment",
                              outcome="success", importance=0.8)
        mem = sigil.memory.get(mid)
        assert mem["outcome"] == "success"

    def test_recall_with_table_filter(self, sigil):
        sigil.remember("Semantic fact A", type="semantic")
        sigil.remember("Episode B", type="episodic",
                        summary="Episode B")
        results = sigil.memory.recall("fact", top_k=10,
                                        tables=["semantic"])
        for r in results:
            assert r.table == "semantic"

    def test_recall_scoring_order(self, sigil):
        sigil.remember("Python is essential for ML", type="semantic",
                        importance=0.9)
        sigil.remember("Python was mentioned briefly", type="semantic",
                        importance=0.1)
        results = sigil.recall("Python ML", top_k=2)
        if len(results) >= 2:
            assert results[0].score >= results[1].score

    def test_delete_nonexistent(self, sigil):
        # Should not raise
        sigil.memory.delete("nonexistent_id_xyz")

    def test_procedural_with_steps(self, sigil):
        mid = sigil.remember("Deploy flow", type="procedural",
                              name="deploy_v2",
                              steps=["build", "test", "push"])
        mem = sigil.memory.get(mid)
        assert mem["name"] == "deploy_v2"
        steps = json.loads(mem["steps"])
        assert len(steps) == 3

    def test_working_memory_max_items(self, sigil):
        """Sigil enforces wm_max_items."""
        # Default max is 10000, but we can test the eviction path
        conn = sigil.memory._get_conn()
        count = conn.execute("SELECT COUNT(*) as c FROM working").fetchone()["c"]
        assert count < sigil.memory.wm_max_items


# ── Extended Knowledge Graph Tests ───────────────────────────────

class TestKnowledgeGraphExtended:

    def test_triple_with_metadata(self, sigil):
        tid = sigil.learn("niam", "knows", "python",
                           metadata={"level": "expert"})
        # Verify by querying
        triples = sigil.graph.query(subject="niam", predicate="knows")
        assert len(triples) == 1
        assert triples[0].object == "python"

    def test_multiple_predicates(self, sigil):
        sigil.learn("niam", "uses", "python")
        sigil.learn("niam", "uses", "typescript")
        sigil.learn("niam", "uses", "react")
        results = sigil.graph.query(subject="niam", predicate="uses")
        assert len(results) == 3

    def test_reverse_query(self, sigil):
        sigil.learn("niam", "uses", "python")
        sigil.learn("zo", "uses", "python")
        results = sigil.graph.query(obj="python")
        assert len(results) == 2

    def test_neighbors(self, sigil):
        sigil.learn("niam", "works_on", "zo")
        sigil.learn("zo", "built_with", "react")
        sigil.learn("react", "type_is", "framework")
        neighbors = sigil.graph.neighbors("niam", depth=2)
        entities = {n.name for n in neighbors}
        assert "zo" in entities

    def test_boost_score(self, sigil):
        sigil.learn("python", "used_for", "data science")
        sigil.learn("python", "type_is", "language")
        boost = sigil.graph.boost_score("Python is a language", "language")
        # Should return some boost (not necessarily large, but >= 0)
        assert boost >= 0

    def test_graph_fts_search(self, sigil):
        sigil.learn("sigil", "type_is", "memory_system")
        results = sigil.graph.search("memory")
        assert len(results) > 0


# ── Extended A2A Bridge Tests ────────────────────────────────────

class TestA2ABridgeExtended:

    def test_wildcard_handler(self, sigil):
        received = []
        sigil.sync.on("*", lambda e: received.append(e))
        sigil.sync.emit("any_event", {"data": 1})
        sigil.sync.emit("other_event", {"data": 2})
        assert len(received) == 2

    def test_event_with_memory_ref(self, sigil):
        mid = sigil.remember("Shared decision", type="semantic")
        eid = sigil.sync.emit("memory_shared", {"mid": mid},
                               memory_id=mid, memory_table="semantic")
        assert eid.startswith("evt_")

    def test_bridge_stats(self, sigil):
        sigil.sync.emit("test", {"x": 1})
        sigil.sync.emit("test", {"x": 2})
        stats = sigil.sync.stats()
        assert stats["total_events"] >= 2


# ── Extended Project Manager Tests ───────────────────────────────

class TestProjectManagerExtended:

    def test_project_list(self, sigil):
        sigil.project.create("proj1")
        sigil.project.create("proj2")
        projects = sigil.project.list_projects()
        assert len(projects) >= 2

    def test_task_assignee(self, sigil):
        pid = sigil.project.create("assign-test")
        tid = sigil.project.add_task(pid, "Code review", assignee="hermes")
        tasks = sigil.project.list_tasks(pid)
        assigned = [t for t in tasks if t.assignee == "hermes"]
        assert len(assigned) == 1

    def test_task_priority_ordering(self, sigil):
        pid = sigil.project.create("priority-test")
        sigil.project.add_task(pid, "Low task", priority="low")
        sigil.project.add_task(pid, "Critical task", priority="critical")
        sigil.project.add_task(pid, "Medium task", priority="medium")
        status = sigil.project.status(pid)
        assert status["total_tasks"] == 3

    def test_update_task_status(self, sigil):
        pid = sigil.project.create("update-test")
        tid = sigil.project.add_task(pid, "Work item")
        sigil.project.update_task(tid, status="completed")
        status = sigil.project.status(pid)
        assert status["progress"] == 100.0

    def test_project_with_deadline(self, sigil):
        pid = sigil.project.create("deadline-test",
                                    deadline="2025-12-31")
        projects = sigil.project.list_projects()
        found = [p for p in projects if p.id == pid]
        assert len(found) == 1


# ── Extended Entity Linking Tests ────────────────────────────────

class TestEntityLinkingExtended:

    def test_extract_urls(self, sigil):
        entities = sigil.entities.extract_entities(
            "Check https://zo.computer for details")
        types = {e["type"] for e in entities}
        assert "url" in types

    def test_extract_emails(self, sigil):
        entities = sigil.entities.extract_entities(
            "Contact niam@zo.space for info")
        types = {e["type"] for e in entities}
        assert "email" in types

    def test_extract_handles(self, sigil):
        entities = sigil.entities.extract_entities(
            "Follow @niam on social media")
        values = {e["value"] for e in entities}
        assert "@niam" in values

    def test_extract_file_paths(self, sigil):
        entities = sigil.entities.extract_entities(
            "Edit /home/niam/config.yaml to change settings")
        types = {e["type"] for e in entities}
        assert "file" in types

    def test_stop_entities_excluded(self, sigil):
        entities = sigil.entities.extract_entities("Here There Now Then")
        values = {e["value"] for e in entities}
        assert "Here" not in values
        assert "There" not in values

    def test_co_occurrence_links(self, sigil):
        sigil.remember("Niam uses Python and Docker together",
                        type="semantic")
        stats = sigil.entities.stats()
        assert stats["co_occurrence_links"] > 0

    def test_entity_boost_no_overlap(self, sigil):
        boost = sigil.entities.entity_boost("weather today", "database schema design")
        assert boost == 0.0


# ── Extended Consolidation Tests ─────────────────────────────────

class TestConsolidationExtended:

    def test_condense_single(self, sigil):
        result = sigil.consolidator._condense(["Single memory"])
        assert result == "Single memory"

    def test_condense_multiple(self, sigil):
        result = sigil.consolidator._condense([
            "First thing happened",
            "Second thing occurred",
            "Third event took place",
        ])
        assert "First thing" in result
        assert "Second thing" in result

    def test_condense_dedup(self, sigil):
        result = sigil.consolidator._condense([
            "Same content here",
            "Same content here",
            "Different content",
        ])
        assert result.count("Same content") == 1

    def test_detect_surprises_empty(self, sigil):
        # With no existing memories, no surprises
        surprises = sigil.consolidator.detect_surprises("Brand new info")
        assert len(surprises) == 0


# ── Extended Compression Tests ───────────────────────────────────

class TestCompressionExtended:

    def test_filler_removal(self):
        comp = AAKCompressor()
        result = comp.compress("It is essentially basically just a thing")
        assert "essentially" not in result
        assert "basically" not in result

    def test_whitespace_collapse(self):
        comp = AAKCompressor()
        result = comp.compress("Too    many     spaces    here")
        assert "    " not in result

    def test_compress_empty(self):
        comp = AAKCompressor()
        result = comp.compress("")
        assert result == ""

    def test_compress_preserves_meaning(self):
        comp = AAKCompressor()
        original = "In order to deploy the service we need to build it first"
        result = comp.compress(original)
        assert "deploy" in result
        assert "build" in result

    def test_compress_memories_empty(self):
        comp = AAKCompressor()
        result = comp.compress_memories([], max_tokens=500)
        assert result == ""


# ── Stagnation Detector Unit Tests ───────────────────────────────

class TestStagnationDetector:

    def test_unique_outputs_healthy(self):
        sd = StagnationDetector()
        for i in range(5):
            result = sd.check_output(f"Unique output {i}")
            assert not result["is_repetitive"]

    def test_repetitive_triggers(self):
        sd = StagnationDetector()
        sd.check_output("same")
        sd.check_output("same")
        result = sd.check_output("same")
        assert result["is_repetitive"]
        assert result["repetition_count"] >= 2

    def test_progress_no_plateau_with_growth(self):
        sd = StagnationDetector()
        for i in range(5):
            result = sd.check_progress(i * 0.2)
        assert not result["is_plateau"]

    def test_progress_plateau(self):
        sd = StagnationDetector()
        for _ in range(6):
            result = sd.check_progress(0.5)
        assert result["is_plateau"]

    def test_history_limit(self):
        sd = StagnationDetector(max_history=5)
        for i in range(10):
            sd.check_output(f"output {i}")
        assert len(sd._output_hashes) == 5


# ── Integration Tests ────────────────────────────────────────────

class TestIntegration:

    def test_remember_recall_cycle(self, sigil):
        """Full cycle: remember -> recall -> verify."""
        sigil.remember("Sigil is the best memory system", type="semantic",
                        importance=0.9)
        sigil.remember("Built Sigil with Python and SQLite", type="episodic",
                        summary="Built Sigil with Python and SQLite",
                        outcome="success")
        sigil.learn("sigil", "built_with", "python")
        sigil.learn("sigil", "built_with", "sqlite")

        results = sigil.recall("Sigil memory system", top_k=5)
        assert len(results) > 0
        assert any("Sigil" in r.content or "sigil" in r.content.lower()
                    for r in results)

    def test_persona_with_activation(self, sigil):
        """Persona + PKA generates useful system prompt."""
        sigil.set_persona("engineer")
        sigil.remember("Auth service has a JWT refresh bug", type="episodic",
                        summary="Auth service has a JWT refresh bug",
                        outcome="pending", importance=0.9)
        prompt = sigil.system_prompt(context="fixing authentication bugs")
        assert "engineer" in prompt.lower() or "software" in prompt.lower()

    def test_multi_agent_workflow(self, tmp_db):
        """Two agents sharing a database can coordinate."""
        zo = Sigil(db_path=tmp_db, agent_id="zo")
        hermes = Sigil(db_path=tmp_db, agent_id="hermes")

        # Zo makes a decision (remember also emits sync events internally)
        zo.remember("Decided to use PostgreSQL for production", type="semantic")
        zo.learn("project", "database", "postgresql")
        zo.sync.emit("decision", {"what": "Use PostgreSQL"})

        # Hermes picks up all events from Zo
        events = hermes.sync.pull()
        assert len(events) >= 1
        decision_events = [e for e in events if e.event_type == "decision"]
        assert len(decision_events) == 1
        assert decision_events[0].payload["what"] == "Use PostgreSQL"

        # Hermes can query Zo's graph entries via the shared DB
        # (graph is agent-scoped, so query with zo's agent_id)
        triples = zo.graph.query(subject="project", predicate="database")
        assert len(triples) == 1
        assert triples[0].object == "postgresql"

        zo.close()
        hermes.close()

    def test_orchestrate_with_memory(self, sigil):
        """Swarm results get saved as episodic memories."""
        def mock(prompt, tier):
            return f"Done: {prompt}"

        sigil.swarm.register_executor("default", mock)
        result = sigil.orchestrate([
            {"id": "research", "prompt": "Research best practices"},
            {"id": "implement", "prompt": "Build it", "depends_on": ["research"]},
        ])
        assert result.success_count == 2

        # Check that episodic memory was created for the swarm run
        count = sigil.memory.count()
        assert count["episodic"] >= 1

    def test_health_check_flow(self, sigil):
        """Realistic health check scenario."""
        # Normal operation
        result = sigil.check_health(output="Processing request A", progress=0.2)
        assert result["healthy"]

        result = sigil.check_health(output="Processing request B", progress=0.4)
        assert result["healthy"]

        # Error occurs
        result = sigil.check_health(error="Timeout connecting to API",
                                     context="email sending")
        assert result["healthy"]  # First occurrence is fine

        # Same error again
        result = sigil.check_health(error="Timeout connecting to API",
                                     context="email reading")
        assert not result["healthy"]
        assert "recurring_failure" in result["issues"]

    def test_full_stats(self, sigil):
        """Stats includes all subsystems including persona."""
        sigil.remember("Test fact", type="semantic")
        sigil.learn("a", "b", "c")
        sigil.set_persona("engineer")

        stats = sigil.stats()
        assert "memory" in stats
        assert "graph" in stats
        assert "persona" in stats
        assert stats["persona"]["active_persona"] == "Engineer"

    def test_context_manager_full(self, tmp_db):
        """Context manager properly initializes and cleans up."""
        with Sigil(db_path=tmp_db, agent_id="ctx") as cx:
            cx.remember("Test", type="semantic")
            cx.learn("a", "b", "c")
            cx.set_persona("writer")
            assert cx.memory.count()["semantic"] == 1
            assert cx.persona.active_persona()["name"] == "Writer"

    def test_repr(self, sigil):
        r = repr(sigil)
        assert "Sigil" in r
        assert "test" in r


# ── Audit Fix Tests ──────────────────────────────────────────────

class TestAuditFixes:
    """Tests verifying all audit findings were properly fixed."""

    def test_import_json_rejects_malicious_columns(self, sigil, tmp_db):
        """CRITICAL: SQL injection via column names in import_json is blocked."""
        export_path = tmp_db + ".export.json"
        # Craft malicious JSON with injected column names
        malicious_data = {
            "version": 4,
            "agent_id": "test",
            "exported_at": "2026-01-01",
            "semantic": [{
                "id": "sem_safe123",
                "content": "Safe content",
                "category": "general",
                "importance": 0.5,
                "source": "user",
                "agent_id": "test",
                "created_at": "2026-01-01T00:00:00.000000",
                "updated_at": "2026-01-01T00:00:00.000000",
                "access_count": 0,
                "decay_class": "standard",
                "metadata": "{}",
                # This malicious key should be stripped
                "id); DROP TABLE semantic; --": "pwned",
            }],
        }
        with open(export_path, "w") as f:
            json.dump(malicious_data, f)

        try:
            sigil.import_json(export_path)
            # Table should still exist and contain the imported record
            conn = sigil.memory._get_conn()
            row = conn.execute("SELECT * FROM semantic WHERE id = 'sem_safe123'").fetchone()
            assert row is not None
            assert row["content"] == "Safe content"
        finally:
            os.unlink(export_path)

    def test_import_json_skips_rows_without_id(self, sigil, tmp_db):
        """Import skips rows that have no 'id' field after whitelisting."""
        export_path = tmp_db + ".export2.json"
        malicious_data = {
            "version": 4,
            "agent_id": "test",
            "exported_at": "2026-01-01",
            "semantic": [{
                "bad_column": "no_id_here",
            }],
        }
        with open(export_path, "w") as f:
            json.dump(malicious_data, f)
        try:
            # Should not raise
            sigil.import_json(export_path)
        finally:
            os.unlink(export_path)

    def test_working_memory_searchable_via_recall(self, sigil):
        """HIGH: Working memory should be findable via recall()."""
        sigil.memory.remember_working(
            "The deployment target is kubernetes on GCP",
            importance=0.9, session_id="s1"
        )
        # Recall should find it via FTS
        results = sigil.recall("kubernetes deployment", top_k=5)
        found = any("kubernetes" in r.content.lower() for r in results)
        assert found, "Working memory not found via recall() — FTS not working"

    def test_working_memory_eviction_cleans_vectors(self, sigil):
        """Working memory eviction should also remove vectors."""
        mid = sigil.memory.remember_working("temp data", ttl_hours=1)
        conn = sigil.memory._get_conn()
        # Manually set expiry to the past to force eviction
        conn.execute(
            "UPDATE working SET expires_at = '2020-01-01T00:00:00.000000' WHERE id = ?",
            (mid,)
        )
        conn.commit()
        sigil.memory._evict_working()
        vec = conn.execute(
            "SELECT * FROM vectors WHERE memory_id = ?", (mid,)
        ).fetchone()
        wm = conn.execute(
            "SELECT * FROM working WHERE id = ?", (mid,)
        ).fetchone()
        assert wm is None
        assert vec is None

    def test_entity_linking_no_duplicate_triples(self, sigil):
        """HIGH: Repeated link_memory calls should not create duplicate triples."""
        mid = sigil.remember("Python and Docker are great", type="semantic")
        conn = sigil.memory._get_conn()

        count_before = conn.execute(
            "SELECT COUNT(*) as c FROM triples WHERE source = 'entity_linking'"
        ).fetchone()["c"]

        # Call link_memory again with same content
        sigil.entities.link_memory(mid, "semantic", "Python and Docker are great")

        count_after = conn.execute(
            "SELECT COUNT(*) as c FROM triples WHERE source = 'entity_linking'"
        ).fetchone()["c"]

        assert count_after == count_before, \
            f"Duplicate triples created: {count_before} -> {count_after}"

    def test_entity_cooccurrence_confidence_grows(self, sigil):
        """Co-occurrence triples should gain confidence on re-encounter."""
        sigil.remember("Python with Docker setup", type="semantic")
        conn = sigil.memory._get_conn()

        # Find the co-occurrence triple
        triple1 = conn.execute(
            """SELECT confidence FROM triples
               WHERE predicate = 'co_occurs_with' AND source = 'entity_linking'
               LIMIT 1"""
        ).fetchone()
        initial_conf = triple1["confidence"] if triple1 else 0.6

        # Store another memory with same entities
        mid2 = sigil.remember("Docker and Python integration", type="semantic")
        sigil.entities.link_memory(mid2, "semantic", "Docker and Python integration")

        triple2 = conn.execute(
            """SELECT confidence FROM triples
               WHERE predicate = 'co_occurs_with' AND source = 'entity_linking'
               LIMIT 1"""
        ).fetchone()

        assert triple2["confidence"] >= initial_conf, \
            "Co-occurrence confidence should increase on re-encounter"

    def test_count_is_agent_scoped(self, tmp_db):
        """MEDIUM: count() should only count current agent's memories."""
        cx1 = Sigil(db_path=tmp_db, agent_id="agent_a")
        cx2 = Sigil(db_path=tmp_db, agent_id="agent_b")
        try:
            cx1.remember("Fact for agent A", type="semantic")
            cx1.remember("Another A fact", type="semantic")
            cx2.remember("Fact for agent B", type="semantic")

            assert cx1.memory.count()["semantic"] == 2
            assert cx2.memory.count()["semantic"] == 1
        finally:
            cx1.close()
            cx2.close()

    def test_export_is_agent_scoped(self, tmp_db):
        """MEDIUM: export_json() should only export current agent's data."""
        cx1 = Sigil(db_path=tmp_db, agent_id="agent_a")
        cx2 = Sigil(db_path=tmp_db, agent_id="agent_b")
        export_path = tmp_db + ".scoped.json"
        try:
            cx1.remember("Secret A fact", type="semantic")
            cx2.remember("Secret B fact", type="semantic")

            cx1.export_json(export_path)
            with open(export_path) as f:
                data = json.load(f)

            # Should only have agent_a's data
            contents = [row["content"] for row in data["semantic"]]
            assert "Secret A fact" in contents
            assert "Secret B fact" not in contents
        finally:
            cx1.close()
            cx2.close()
            if os.path.exists(export_path):
                os.unlink(export_path)

    def test_vector_dimension_mismatch_skipped(self, sigil):
        """MEDIUM: Vectors with wrong dimensions should be skipped, not crash."""
        conn = sigil.memory._get_conn()
        import struct
        # Insert a memory with a fake small vector (wrong dimensions)
        conn.execute(
            """INSERT INTO semantic (id, content, category, importance, source,
               agent_id, created_at, updated_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("sem_dimtest", "dimension test content", "general", 0.5, "user",
             "test", "2026-01-01T00:00:00.000000", "2026-01-01T00:00:00.000000", "{}")
        )
        # Store a 10-dimensional vector (should be 384)
        bad_vec = struct.pack("10f", *([0.1] * 10))
        conn.execute(
            """INSERT INTO vectors (id, memory_id, memory_table, embedding, dimensions, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("vec_dimtest", "sem_dimtest", "semantic", bad_vec, 10, "2026-01-01T00:00:00.000000")
        )
        conn.commit()

        # This should not crash
        results = sigil.recall("dimension test", top_k=5)
        # It may or may not find it via FTS, but should not crash

    def test_contradiction_detection_uses_index(self, sigil):
        """MEDIUM: Contradiction detection should work correctly after optimization."""
        sigil.remember("Niam lives in Manila", type="semantic")
        sigil.learn("niam", "lives_in", "Manila")

        # Add a contradicting memory
        sigil.remember("Niam lives in Singapore", type="semantic")

        contradictions = sigil.consolidator.detect_contradictions(limit=10)
        # Should detect the contradiction between "lives in Singapore"
        # and the graph triple "niam lives_in Manila"
        found = any("niam" in c.get("graph_triple", "").lower() for c in contradictions)
        assert found, "Contradiction detection failed after optimization"

    def test_schema_migration_infrastructure(self, tmp_db):
        """LOW: Migration system should work on fresh and existing databases."""
        from sigil.memory.schema import SCHEMA_VERSION, migrate
        cx = Sigil(db_path=tmp_db, agent_id="migrate_test")
        conn = cx.memory._get_conn()

        # Check version is current
        row = conn.execute(
            "SELECT value FROM sigil_meta WHERE key = 'schema_version'"
        ).fetchone()
        assert int(row["value"]) == SCHEMA_VERSION

        # working_fts table should exist
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='working_fts'"
        ).fetchall()
        assert len(tables) == 1
        cx.close()
