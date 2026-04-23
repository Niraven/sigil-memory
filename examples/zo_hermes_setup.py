"""
Sigil setup for Zo + Hermes dual-agent architecture.
Shows how to replace 8 memory stores with one Sigil instance per agent.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sigil import Sigil

# Shared event file for cross-process sync
# Both agents append to this. Each drains the other's events.
EVENT_FILE = "/tmp/sigil-events.jsonl"

# ── ZO SETUP (Cloud Agent) ──

def setup_zo():
    """Initialize Sigil for Zo (cloud agent)."""
    zo = Sigil(
        db_path="/tmp/sigil-zo.db",  # In production: ~/MEMORY/sigil.db
        agent_id="zo",
        event_file=EVENT_FILE,
        wm_ttl_hours=24,           # Working memory lives for 24h
        recency_halflife_hours=168, # 1 week recency decay
        budget_limit=10.0,          # $10 budget per swarm run
    )

    # Register what Zo knows about itself
    zo.learn("zo", "runs_on", "cloud")
    zo.learn("zo", "channels", "sms, telegram, discord, email, web")
    zo.learn("zo", "capabilities", "scheduling, oauth integrations, public endpoints")

    # Session start: activate PKA
    brief = zo.activate(
        persona="systems_copilot",
        session_context="",  # Populated from user's first message
        active_projects=["auth-migration", "niamos"]  # From project manager
    )
    print("ZO ACTIVATION BRIEF:")
    print(zo._pka.to_prompt(brief))

    return zo


# ── HERMES SETUP (Desktop Agent) ──

def setup_hermes():
    """Initialize Sigil for Hermes (desktop agent)."""
    hermes = Sigil(
        db_path="/tmp/sigil-hermes.db",  # In production: ~/sigil.db
        agent_id="hermes",
        event_file=EVENT_FILE,
        wm_ttl_hours=48,            # Longer TTL since sessions are longer
        recency_halflife_hours=336,  # 2 week decay (more persistent)
    )

    # Register what Hermes knows about itself
    hermes.learn("hermes", "runs_on", "desktop")
    hermes.learn("hermes", "capabilities", "code, github, n8n, local files, vector memory")

    return hermes


# ── SYNC DEMO ──

def demo_sync():
    """Show how events flow between Zo and Hermes."""
    zo = setup_zo()
    hermes = setup_hermes()

    print("\n" + "=" * 60)
    print("SYNC DEMO")
    print("=" * 60)

    # Zo makes a decision
    zo.remember("Decided to use PostgreSQL for auth service",
                type="episodic", summary="Decided to use PostgreSQL for auth service",
                outcome="decided", importance=0.9)
    zo.sync.emit("decision_made", {
        "topic": "auth-service-db",
        "decision": "PostgreSQL",
        "reason": "pgvector support for future semantic search"
    })
    print("\nZo: Emitted decision event")

    # Hermes pulls events (in real life, this happens via file watcher)
    events = hermes.sync.pull_from_file()
    print(f"Hermes: Pulled {len(events)} events from Zo")
    for e in events:
        print(f"  - [{e.event_type}] {e.payload}")

    # Hermes acts on the decision
    hermes.remember("Zo decided PostgreSQL for auth service",
                    type="semantic", category="decisions", importance=0.9)
    hermes.sync.emit("task_started", {
        "task": "Set up PostgreSQL schema for auth",
        "triggered_by": "zo_decision"
    })
    print("\nHermes: Started task based on Zo's decision")

    # Zo picks up Hermes's response
    zo_events = zo.sync.pull_from_file()
    print(f"Zo: Pulled {len(zo_events)} events from Hermes")
    for e in zo_events:
        print(f"  - [{e.event_type}] {e.payload}")

    print("\nLatency: sub-10ms (file append + read)")
    print("If Hermes is offline: events buffer in JSONL, drain on boot")

    zo.close()
    hermes.close()


# ── REPLACES YOUR CURRENT STACK ──

def show_replacement():
    """Show what Sigil replaces in the current system."""
    print("\n" + "=" * 60)
    print("WHAT SIGIL REPLACES")
    print("=" * 60)

    replacements = [
        ("DuckDB (data.duckdb)", "cx.memory (SQLite)"),
        ("Vector Memory v3 (Hermes)", "cx.recall() with hybrid search"),
        ("Supermemory (10 memories)", "cx.memory.recall() local"),
        ("niam-knowledge-wiki.md", "cx.graph.entity() + cx.graph.query()"),
        ("SESSION-PRIMER.md", "cx.activate() generates fresh each time"),
        ("SESSION-STATE.md", "cx.remember(type='working')"),
        ("hermes-updates.md / zo-updates.md", "cx.sync event bus"),
        ("parked.md", "cx.remember(type='working', category='parked')"),
        ("skill-router.py (222 skills)", "cx.swarm.complexity estimator"),
        ("35 rules", "Sigil PKA + orchestrator handle most rule logic"),
        ("Daily 6pm A2A sync", "Event-driven, sub-10s"),
    ]

    for old, new in replacements:
        print(f"  {old:50s} -> {new}")

    print(f"\n  Total stores: 8 -> 1 SQLite file per agent")
    print(f"  Write paths: 3-5x per fact -> 1x per fact")
    print(f"  Sync latency: 8 hours -> <10 seconds")


if __name__ == "__main__":
    demo_sync()
    show_replacement()
