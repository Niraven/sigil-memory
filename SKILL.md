---
name: sigil
description: Sigil cognitive memory system for Zo + Hermes (shared filesystem). Use for: memory recall, knowledge graph queries, A2A event sync, PKA activation prompts, swarm orchestration, and self-healing. Activate when Niam asks about memory, what was decided, what happened before, what Hermes is working on, or to improve continuous context.
compatibility: Zo Computer (shared filesystem with Hermes)
metadata:
  author: niam.zo.computer
  version: 0.2.0
  installed: 2026-04-24
  status: active
  agent: both (zo + hermes share same sigil.db)
allowed-tools: Bash, Read, Edit
---

# Sigil — Shared Cognitive Memory (Zo + Hermes)

Both agents share one SQLite DB and one event log via the native filesystem.
**DB:** `/home/workspace/MEMORY/sigil.db`
**Event log:** `/home/workspace/MEMORY/shared/sigil-events.jsonl`
**Skill path:** `/home/workspace/Skills/sigil/`

---

## Initialization (do once per session)

```python
import sys
sys.path.insert(0, '/home/workspace/Skills')
from sigil import Sigil

cx = Sigil(
    db_path='/home/workspace/MEMORY/sigil.db',
    event_file='/home/workspace/MEMORY/shared/sigil-events.jsonl',
    agent_id='zo',          # or 'hermes'
)
```

---

## Core API Reference (verified working, v0.2.0)

### `cx.recall(query, top_k=5)` → list[MemoryResult]
Semantic recall. `MemoryResult` has: `.content`, `.score`, `.created_at`, `.table`.
```python
results = cx.recall("niam preferences", top_k=3)
for r in results:
    print(r.score, r.content[:80])
```

### `cx.remember(content, type='semantic', **kwargs)` → memory_id
Store a memory. `type` options: `'semantic'`, `'episodic'`, `'working'`.
```python
cx.remember(
    content="Niam prefers short responses",
    type="episodic",
    importance=0.8,
    tags=["niam", "preference"],
)
```

### `cx.graph.neighbors(entity, depth=1)` → list[Entity]
Entity's knowledge graph connections. `Entity` has: `.name`, `.score`.
```python
nbrs = cx.graph.neighbors("zo", depth=1)
for n in nbrs: print(n.name, n.score)
```

### `cx.graph.query(subject=None, predicate=None, obj=None)` → list[Triple]
Query the knowledge graph.
```python
triples = cx.graph.query(subject="zo")
for t in triples: print(t.subject, t.predicate, t.object)
```

### `cx.activate(persona='default', session_context='')` → dict
PKA briefing — generates activation prompt. Returns dict with keys:
`generated_at`, `persona`, `summary`, `token_estimate`, `sections`.
```python
d = cx.activate(persona='default', session_context='hermes session start')
items = d['sections']['relevant_context']['items']
for item in items: print(item['score'], item['content'][:60])
```

### `cx.sync.pull()` → list[Event]
Pull A2A events from the shared event log. Returns list of Event objects.
```python
events = cx.sync.pull()
print("{} events synced".format(len(events)))
```

### `cx.sync.emit(event_type, payload)` → bool
Emit an A2A event to the shared event log.
```python
cx.sync.emit(
    event_type='memory_created',
    payload={'content': '...', 'source': 'zo'},
)
```

### `cx.health_report()` → dict
System health. Keys: `working_memory`, `stagnation`, `consolidation`, `graph`.

### `cx.stats()` → dict
Sigil stats: memory counts, graph size, event log size.

---

## Swarm API (for parallel /zo/ask fan-outs)

```python
cx.swarm.register_executor(name="research", fn=my_function)
cx.swarm.stats()           # {'pending': N, 'completed': N}
cx.swarm.circuit_breaker   # check if overloaded
```

---

## Hermes Bootstrap Script

Location: `/home/workspace/MEMORY/shared/hermes-sigil-bootstrap.py`
Run once per Hermes session start:
```bash
python3 /home/workspace/MEMORY/shared/hermes-sigil-bootstrap.py
```

---

## Current State (live)

- **Knowledge graph:** zo=10 neighbors, hermes=8 neighbors, niam=20 neighbors
- **Events in log:** 48+ (hermes bootstrapped, both agents synced)
- **Working memory:** active per-session, consolidated on stagnation
- **Status:** ✅ both agents live on Sigil

---

## When to Use

| Situation | Call |
|---|---|
| Niam asks "what did we decide about X" | `cx.recall("X decision")` |
| Niam asks "what's Hermes working on" | `cx.recall("hermes current task")` |
| New fact about Niam or project | `cx.remember()` + `cx.graph.add()` |
| Session start (replace SESSION-PRIMER) | `cx.activate(persona='default', session_context='...')` |
| Something happened on Hermes side | `cx.sync.pull()` |
| Want to tell Hermes something | `cx.sync.emit()` |
| Parallel research fan-out | `cx.swarm.orchestrate()` |
| Checking system health | `cx.health_report()` |

---

## What Sigil Replaces

| Old way | Sigil way |
|---|---|
| SESSION-PRIMER.md (stale file) | `cx.activate()` — fresh PKA each session |
| niam-knowledge-wiki.md (manual) | `cx.recall()` — semantic query |
| hermes-updates.md / zo-updates.md (daily batch) | `cx.sync.emit/pull()` — event-driven A2A |
| Write-twice to DuckDB + wiki | `cx.remember()` — single write, both derive |
| 35 rules, many contradictory | Sigil's memory handles continuity; rules stay lean |
