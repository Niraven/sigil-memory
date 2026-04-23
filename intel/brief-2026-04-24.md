# AI Agent Intelligence Brief — 2026-04-24

## TL;DR
1. **Prism paper (arxiv 2604.19795) beats Mem0 by 31% on LoCoMo** — their entropy-gated stratification + causal memory graph + replicator-decay dynamics are ideas we should steal for Sigil v0.3
2. **Manifest (5.5k stars, trending)** does 23-dimension model routing in <2ms — our ComplexityEstimator has 9 signals, we should upgrade to match and offer Sigil as a routing layer
3. **FSFM paper introduces selective forgetting** as first-class capability — Sigil's sleep consolidation only compresses, doesn't strategically forget. Adding decay-based pruning + safety-triggered deletion would leapfrog Mem0/Zep

---

## What's New in Agent Frameworks

### Manifest (mnfst/manifest) — 5.5k stars, +1.2k/week
- **What:** Smart model routing for AI agents. 23-dimension scoring in <2ms, 4 tiers (simple/standard/complex/reasoning), runs locally
- **For Sigil:** Our `ComplexityEstimator` does the same thing with 9 signals. We should expand to 20+ signals and offer Sigil's model routing as standalone middleware. This validates our architecture.
- **Action:** Upgrade ComplexityEstimator to match Manifest's 23 dimensions. Add provider fallback chains.

### Letta (formerly MemGPT) — 22k stars
- **What:** Stateful agents with memory_blocks (named segments like "human", "persona"). Agents can modify their own memory. Skills + subagents architecture.
- **For Sigil:** We have this via working memory + persona system. Their "agents modify own memory" pattern maps to our `evolve_procedure()`. We're architecturally comparable but need better docs.
- **Gap:** Letta has REST API + TypeScript SDK. Sigil is Python-only CLI. **We need an HTTP server.**

### n8n — 185k stars
- **What:** Visual workflow automation with native AI. 400+ integrations.
- **For Sigil:** Not competitive — different layer. But we could build a Sigil MCP server that n8n/LangChain/CrewAI can consume.

---

## Memory & RAG Landscape

### Mem0 — 54k stars (our primary benchmark)
**New algorithm (April 2026):**
| Benchmark | Mem0 | Sigil (est.) |
|-----------|------|-------------|
| LoCoMo | 91.6 | ~75-80* |
| LongMemEval | 93.4 | untested |
| BEAM (1M) | 64.1 | untested |

*Sigil estimate based on architecture comparison. We need to actually run these benchmarks.

**Key Mem0 advantages we need to close:**
1. ADD-only extraction (single LLM call) — we don't use LLM for extraction
2. spaCy NER for entity linking — we use regex patterns
3. Cloud deployment option — we're local-only (which is a feature, but limits market)

**Where Sigil wins over Mem0:**
1. Zero cloud dependencies (Mem0 requires OpenAI by default)
2. Temporal knowledge graph with auto-invalidation (Mem0 has entity linking but no temporal validity)
3. Procedural memory with self-evolution (Mem0 doesn't have this)
4. Sleep consolidation (Mem0 doesn't have this)
5. Swarm orchestration built-in (Mem0 is memory-only)
6. Self-healing + capability gap tracking (unique to Sigil)

### Zep — "Context Engineering Platform"
- Pivoted to cloud-first, deprecated community edition
- Their Graphiti temporal knowledge graph is strong competition
- **Key feature:** `valid_at` / `invalid_at` timestamps — **we already have this** (valid_from/valid_until)
- SOC2/HIPAA compliance for enterprise — market opportunity Sigil could fill for local-first deployments

### Prism (arxiv 2604.19795) — MOST IMPORTANT PAPER THIS WEEK
**88.1 on LoCoMo (31% above Mem0)** with these innovations:
1. **Entropy-gated stratification** — route memories to skills/notes/attempts based on information content
2. **Causal memory graph** — tracks which agent contributed what, with interventional edges
3. **Value-of-Information retrieval** — don't retrieve everything, retrieve what has highest expected value
4. **Heartbeat-driven consolidation** — detect stagnation via optimal stopping theory
5. **Replicator-decay dynamics** — memory confidence treated as evolutionary fitness

**What to steal for Sigil v0.3:**
- Entropy gating for memory routing (instead of explicit type selection)
- Value-of-Information retrieval policy (replace fixed 50/30/10/10 weights)
- Replicator dynamics for confidence decay (instead of linear decay)
- Agent provenance on shared memories (who contributed what)

---

## Buildable This Week

Ranked by impact/effort:

| # | What | Why | Effort | Impact |
|---|------|-----|--------|--------|
| 1 | **MCP Server for Sigil** | Any MCP-compatible tool (n8n, Continue, Cursor, etc.) can use Sigil as memory | 2 days | HIGH |
| 2 | **Selective forgetting module** (FSFM-inspired) | Pruning is as important as storing. Add decay curves + safety deletion | 2 days | HIGH |
| 3 | **LoCoMo benchmark runner** | We need actual numbers to compare against Mem0's 91.6 | 1 day | HIGH |
| 4 | **HTTP REST API** | Letta has one, Mem0 has one — we need one for non-Python agents | 2 days | HIGH |
| 5 | **Entropy-gated memory routing** (Prism-inspired) | Auto-classify memories by information content instead of manual type selection | 3 days | MEDIUM |
| 6 | **Expand ComplexityEstimator to 20+ signals** (Manifest-inspired) | Match Manifest's routing quality, position as standalone model router | 2 days | MEDIUM |
| 7 | **DPM append-only mode** for enterprise/audit trails | Single-projection replay instead of N summarization calls | 3 days | MEDIUM |

---

## SaaS / Product Ideas

| # | Idea | Target Market | Why Now | MVP Effort |
|---|------|--------------|---------|------------|
| 1 | **"Sigil Cloud" — managed memory-as-a-service for SEA startups** | SEA AI startups who can't afford Mem0/Zep pricing | Zep deprecated free tier, Mem0 requires OpenAI. Local-first + affordable = gap | 2 weeks |
| 2 | **"Agent Memory Audit" consulting service** | Enterprise clients with multiple AI agents | Use Sigil to audit, consolidate, and optimize existing agent memory | 0 (use existing Sigil) |
| 3 | **Model routing middleware** (Manifest competitor, SEA-focused) | Companies paying too much for LLM APIs | Manifest proves demand. SEA angle: optimize for local model providers | 1 week |
| 4 | **"AI Agent Health Dashboard"** | DevOps teams running AI agents in production | Sigil's self-heal + capability gaps as a monitoring SaaS | 2 weeks |
| 5 | **Philippine BPO AI Agent toolkit** | BPO companies automating customer service | PH is the #1 BPO market. Agent memory + persona system = custom CS agents | 3 weeks |

---

## Thought Leadership Content

| # | Topic | Angle | Platform | Why It Hits |
|---|-------|-------|----------|-------------|
| 1 | **"Why Your AI Agent Needs to Forget"** | FSFM paper + Sigil's approach to memory lifecycle | Blog + Twitter thread | Counterintuitive — everyone talks about remembering, nobody talks about forgetting |
| 2 | **"I Built a Memory System That Beats Mem0's Architecture"** | Technical deep-dive on Sigil's temporal graph + 5-signal retrieval | Dev.to + HackerNews | Provocative claim backed by real code (open source) |
| 3 | **"The Model Routing Problem Nobody's Solving Right"** | Compare Manifest vs Sigil vs OpenRouter approaches | Blog | Trending topic (Manifest just hit 5.5k stars) |
| 4 | **"Zero-Cloud AI: Why Philippine Companies Should Own Their Agent Memory"** | Data sovereignty + cost argument for local-first AI in SEA | LinkedIn + local tech events | Resonates with enterprise buyers worried about data leaving PH |
| 5 | **"From BPO to AI: Building the Philippine Agent Economy"** | Vision piece on PH's unique position to lead in AI agents | LinkedIn + speaking slot at local tech conference | Positions Niam as the thought leader at the intersection of PH + AI |

---

## Sigil Roadmap Recommendations

Based on competitive landscape:

### v0.3 (Next 2 weeks)
1. **MCP Server** — expose Sigil via MCP for universal tool integration
2. **REST API** — `sigil serve` command, FastAPI-based
3. **Selective forgetting** — decay curves, safety deletion, entropy-based routing
4. **LoCoMo + LongMemEval benchmark suite** — get real numbers

### v0.4 (Month 2)
5. **Value-of-Information retrieval** (Prism-inspired) — adaptive weight fusion
6. **Expanded model routing** (20+ signals, Manifest-inspired)
7. **Agent provenance** — track which agent contributed each memory
8. **DPM mode** — append-only for enterprise audit trails

### v0.5 (Month 3)
9. **sqlite-vec ANN search** — replace brute-force vector scan
10. **LLM-powered extraction** — optional spaCy/LLM NER for entity linking
11. **TypeScript SDK** — for non-Python agents
12. **Dashboard UI** — web-based Sigil explorer

---

## SEA / Philippines Opportunities

| # | Opportunity | Market Size | Competition | Our Angle |
|---|------------|-------------|-------------|-----------|
| 1 | **BPO AI Agent Platform** | $38B PH BPO industry | Generic tools (Zendesk AI, etc.) | Purpose-built for Filipino CS context, Tagalog support, local deployment |
| 2 | **Local-first AI Memory for PH banks** | BSP-regulated, data sovereignty required | None (Mem0/Zep are US cloud) | Sigil is zero-cloud, runs on-prem. Perfect for BSP compliance |
| 3 | **AI Consultant Network** | Growing SEA AI adoption | Few credible AI consultants in PH | Niam + Sigil as the platform = consulting + tool revenue |
| 4 | **SEA AI Agent Marketplace** | Emerging | Nothing exists yet | Build agents with Sigil, sell via marketplace. First mover in SEA |
| 5 | **Government AI automation** | Large PH gov tech budget | IBM, Accenture (expensive) | Local, affordable, open-source story |

---

## Key Papers to Read

| Paper | ID | Key Insight for Sigil |
|-------|-----|----------------------|
| FSFM: Selective Forgetting | 2604.20300 | Forgetting taxonomy: passive decay, active deletion, safety-triggered, adaptive reinforcement |
| Prism: Evolutionary Memory | 2604.19795 | Entropy gating, causal graph, replicator dynamics — beats Mem0 by 31% |
| Stateless Decision Memory | 2604.20158 | DPM: append-only + single projection = 7-15x faster, auditable |
| Self-Awareness Before Action | 2604.20413 | PKA should audit knowledge completeness before acting, not just retrieve |
| EvoAgent | 2604.20133 | Self-evolving agents with skill learning — maps to our procedural evolution |
| Automatic Ontology via LLM | 2604.20795 | LLM as external memory layer for ontology building — could enhance our graph |

---

## Raw Sources
- https://github.com/trending (weekly, April 2026)
- https://github.com/mnfst/manifest
- https://github.com/mem0ai/mem0
- https://github.com/getzep/zep
- https://github.com/letta-ai/letta
- https://github.com/modelcontextprotocol/servers
- https://arxiv.org/abs/2604.20300
- https://arxiv.org/abs/2604.19795
- https://arxiv.org/abs/2604.20158
- https://arxiv.org/abs/2604.20413
- https://arxiv.org/abs/2604.20133
- https://arxiv.org/abs/2604.20795
- https://news.ycombinator.com/
- https://www.producthunt.com/topics/artificial-intelligence
