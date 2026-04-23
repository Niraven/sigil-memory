#!/usr/bin/env python3
"""
Sigil CLI wrapper for Zo — run via:
  python3 /home/workspace/Skills/sigil/scripts/sigil_wrapper.py <command> [args_json]

Commands:
  remember  {"content": "...", "type": "semantic|episodic|procedural|working", "importance": 0.7}
  recall    {"query": "...", "top_k": 5}
  activate  {"persona": "engineer|researcher|strategist|operator|critic|systems_copilot", "context": "..."}
  emit      {"event_type": "...", "payload": {...}}
  pull      {}
  graph_add {"subject": "...", "predicate": "...", "object": "...", "confidence": 0.95}
  about     {"entity": "..."}
  stats     {}
  health    {"output": "...", "error": "...", "context": "..."}
  personas  {}
  sleep     {"max_age_hours": 24}
  complexity {"task": "..."}
"""
import sys, json, os
sys.path.insert(0, '/home/workspace/Skills')
from sigil import Sigil

SIGIL_PATH = "/home/workspace/MEMORY/sigil.db"
EVENT_FILE = "/home/workspace/MEMORY/shared/sigil-events.jsonl"

def get_cx():
    return Sigil(db_path=SIGIL_PATH, event_file=EVENT_FILE, agent_id="zo")

COMMANDS = {
    "remember": lambda cx, a: {"id": cx.remember(
        a["content"],
        type=a.get("type", "semantic"),
        importance=a.get("importance", 0.7),
        outcome=a.get("outcome"),
    )},
    "recall": lambda cx, a: [
        {"content": r.content, "score": r.score, "table": r.table, "id": r.id}
        for r in cx.recall(a["query"], top_k=a.get("top_k", 5))
    ],
    "activate": lambda cx, a: cx.activation_prompt(
        persona=a.get("persona", "systems_copilot"),
        session_context=a.get("context", "")
    ),
    "emit": lambda cx, a: (cx.sync.emit(a["event_type"], a.get("payload", {})), {"status": "emitted"})[1],
    "pull": lambda cx, a: [str(e) for e in cx.sync.pull()],
    "graph_add": lambda cx, a: {"id": cx.learn(
        a["subject"], a["predicate"], a["object"],
        confidence=a.get("confidence", 0.95)
    )},
    "about": lambda cx, a: (lambda e: {
        "name": e.name,
        "facts": [(f.subject, f.predicate, f.object, f.confidence) for f in (e.facts() if callable(e.facts) else e.facts)]
    } if e else {"error": "entity not found"})(cx.about(a["entity"])),
    "stats": lambda cx, a: cx.stats(),
    "health": lambda cx, a: (lambda h: {
        "healthy": h.stagnation.get("healthy") if hasattr(h, "stagnation") else True,
        "issues": h.stagnation.get("issues", []) if hasattr(h, "stagnation") else [],
        "recommendations": h.stagnation.get("recommendations", []) if hasattr(h, "stagnation") else [],
    })(cx.check_health(output=a.get("output",""), error=a.get("error"), context=a.get("context",""))),
    "personas": lambda cx, a: {
        "current": str(cx.persona.current) if hasattr(cx, 'persona') else "N/A",
        "available": ["engineer", "researcher", "strategist", "operator", "critic", "systems_copilot"],
    },
    "sleep": lambda cx, a: (cx.sleep(max_age_hours=a.get("max_age_hours", 24)), {"status": "consolidated"})[1],
    "complexity": lambda cx, a: cx.swarm.complexity.estimate(a["task"]) if a.get("task") else {"error": "task required"},
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else (print(__doc__) or sys.exit(0))
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    cx = get_cx()
    fn = COMMANDS.get(cmd)
    if not fn:
        print(json.dumps({"error": f"Unknown command: {cmd}", "available": list(COMMANDS.keys())}, indent=2))
        sys.exit(1)
    try:
        result = fn(cx, args)
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        sys.exit(1)
