"""
Sigil Quickstart — shows all major features in ~50 lines.
Run: python3 examples/quickstart.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sigil import Sigil

# Initialize with a temp database
cx = Sigil("/tmp/sigil-demo.db", agent_id="zo")

# ── 1. Remember things ──
print("=== MEMORY ===")
cx.remember("Niam prefers dark mode", type="semantic", importance=0.9, category="preferences")
cx.remember("Niam uses Python and TypeScript", type="semantic", category="tech")
cx.remember("Deployed auth service, migration failed", type="episodic",
            summary="Deployed auth service, migration failed",
            outcome="failed", importance=0.8)
cx.remember("Deploy flow: build > test > migrate > push", type="procedural",
            name="deploy", steps=["build", "test", "migrate", "push"])
cx.remember("Currently debugging auth token refresh", type="working", importance=0.9)
print(f"  Stored 5 memories across 4 types")

# ── 2. Recall with hybrid search ──
print("\n=== RECALL ===")
results = cx.recall("deployment", top_k=3)
for r in results:
    print(f"  [{r.table}] {r.content[:60]}... (score: {r.score:.3f})")

# ── 3. Knowledge graph ──
print("\n=== KNOWLEDGE GRAPH ===")
cx.learn("niam", "works_on", "zo.space")
cx.learn("niam", "uses", "python")
cx.learn("niam", "uses", "typescript")
cx.learn("zo", "runs_on", "cloud")
cx.learn("hermes", "runs_on", "desktop")
cx.learn("niam", "works_at", "old_company",
         valid_from="2024-01-01T00:00:00.000000",
         valid_until="2025-01-01T00:00:00.000000")
cx.learn("niam", "works_at", "zo.computer",
         valid_from="2025-01-01T00:00:00.000000")

entity = cx.about("niam")
print(f"  Entity 'niam': {entity.out_degree} outgoing, {entity.in_degree} incoming triples")
for t in entity.facts():
    print(f"    {t.subject} -> {t.predicate} -> {t.object}")

# ── 4. Proactive activation (PKA) ──
print("\n=== PROACTIVE ACTIVATION ===")
brief = cx.activate(persona="engineer", session_context="auth deployment")
print(f"  Briefing sections: {list(brief['sections'].keys())}")
print(f"  Token estimate: ~{brief['token_estimate']} tokens")

# ── 5. Multi-agent sync ──
print("\n=== A2A SYNC ===")
cx.sync.emit("decision_made", {"content": "Using PostgreSQL for auth service"})
cx.sync.emit("task_started", {"task": "JWT refresh implementation"})
events = cx.sync.recent(limit=5)
print(f"  Emitted 2 events, {len(events)} in history")

# ── 6. Project management ──
print("\n=== PROJECTS ===")
pid = cx.project.create("auth-migration", milestone="v1.0", deadline="2026-05-01")
t1 = cx.project.add_task(pid, "Design JWT schema", priority="high", assignee="hermes")
t2 = cx.project.add_task(pid, "Implement refresh endpoint", depends_on=[t1], assignee="zo")
t3 = cx.project.add_task(pid, "Write integration tests", depends_on=[t2])
cx.project.update_task(t1, status="completed")

status = cx.project.status(pid)
print(f"  Project: {status['project']}")
print(f"  Progress: {status['progress']}%")
print(f"  Next actions: {status['next_actions']}")
print(f"  Blockers: {status['blockers']}")

# ── 7. Orchestration ──
print("\n=== ORCHESTRATION ===")
cx.swarm.register_executor("default", lambda prompt, tier: f"Done: {prompt[:30]}")

result = cx.orchestrate([
    {"id": "research", "prompt": "Research JWT best practices", "model_tier": "light"},
    {"id": "design", "prompt": "Design the token schema", "depends_on": ["research"]},
    {"id": "implement", "prompt": "Build the endpoint", "depends_on": ["design"], "model_tier": "heavy"},
])
print(f"  Swarm: {result.success_count}/{len(result.tasks)} tasks, "
      f"{result.total_time_seconds}s, ${result.total_cost_estimate}")

# ── 8. Stats ──
print("\n=== STATS ===")
stats = cx.stats()
print(f"  Memories: {stats['memory']['memories']}")
print(f"  Triples: {stats['graph']['active_triples']}")
print(f"  Events: {stats['bridge']['total_events']}")
print(f"  DB size: {stats['memory']['db_size_mb']} MB")

cx.close()
print("\nDone. Database at /tmp/sigil-demo.db")
