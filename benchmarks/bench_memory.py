"""
Performance benchmarks for Sigil memory engine.
Run: python3 benchmarks/bench_memory.py
"""

import os
import sys
import time
import tempfile
import statistics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sigil.core import Sigil


def bench(name, fn, iterations=1000):
    """Run a benchmark and print results."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        elapsed = (time.perf_counter() - start) * 1000  # ms
        times.append(elapsed)

    avg = statistics.mean(times)
    p50 = statistics.median(times)
    p95 = sorted(times)[int(len(times) * 0.95)]
    p99 = sorted(times)[int(len(times) * 0.99)]
    total = sum(times)

    print(f"  {name:40s}  avg={avg:.4f}ms  p50={p50:.4f}ms  "
          f"p95={p95:.4f}ms  p99={p99:.4f}ms  total={total:.1f}ms  "
          f"({iterations} iterations)")
    return avg


def main():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        cx = Sigil(db_path=db_path, agent_id="bench")
        print("\n" + "=" * 80)
        print("SIGIL MEMORY BENCHMARKS")
        print("=" * 80)

        # ── Write Benchmarks ──
        print("\n--- WRITES ---")
        counter = [0]

        def write_semantic():
            counter[0] += 1
            cx.memory.remember_semantic(f"Benchmark fact {counter[0]}", importance=0.5)

        def write_episodic():
            counter[0] += 1
            cx.memory.remember_episodic(f"Benchmark event {counter[0]}", outcome="success")

        def write_working():
            counter[0] += 1
            cx.memory.remember_working(f"Benchmark context {counter[0]}")

        def write_triple():
            counter[0] += 1
            cx.graph.add(f"entity_{counter[0]}", "relates_to", f"target_{counter[0]}")

        w_sem = bench("Semantic write", write_semantic, 1000)
        w_epi = bench("Episodic write", write_episodic, 1000)
        w_wm = bench("Working memory write", write_working, 1000)
        w_triple = bench("Knowledge graph triple", write_triple, 1000)

        # ── Read Benchmarks ──
        print("\n--- READS ---")

        # Populate first
        for i in range(500):
            cx.memory.remember_semantic(f"Topic {i}: Python is used for {i} things",
                                        category=f"cat_{i % 10}", importance=i / 500)

        def read_get():
            cx.memory.get("sem_000000000001")  # Will miss, but exercises path

        def read_fts():
            cx.memory.recall("Python programming", top_k=5,
                             tables=["semantic"])

        def read_graph():
            cx.graph.query(subject="entity_1", limit=5)

        def read_graph_search():
            cx.graph.search("entity relates", limit=5)

        r_get = bench("Direct get by ID", read_get, 1000)
        r_fts = bench("FTS5 hybrid recall (500 docs)", read_fts, 500)
        r_graph = bench("Graph query (by subject)", read_graph, 1000)
        r_gs = bench("Graph FTS search", read_graph_search, 500)

        # ── Scale Benchmarks ──
        print("\n--- SCALE (recall latency vs corpus size) ---")

        for size_label, extra_docs in [("1K", 500), ("2K", 1000), ("5K", 3000)]:
            for i in range(extra_docs):
                cx.memory.remember_semantic(f"Scale test doc {i} about various topics")

            def scaled_recall():
                cx.memory.recall("various topics", top_k=5, tables=["semantic"])

            total_docs = cx.memory.count()["semantic"]
            bench(f"Recall @ {total_docs} docs ({size_label})", scaled_recall, 200)

        # ── Compression Benchmarks ──
        print("\n--- COMPRESSION ---")

        test_text = ("In order to fix the bug due to the fact that it was broken "
                     "at this point in time, we basically need to essentially "
                     "rewrite the entire system. " * 10)

        def compress():
            cx.compressor.compress(test_text)

        bench("AAK compression (500 chars)", compress, 1000)

        # ── A2A Bridge Benchmarks ──
        print("\n--- A2A BRIDGE ---")

        def emit():
            cx.sync.emit("bench_event", {"data": "test"})

        def pull():
            cx.sync.recent(limit=10)

        bench("Event emit", emit, 1000)
        bench("Recent events (10)", pull, 1000)

        # ── PKA Benchmarks ──
        print("\n--- PROACTIVE ACTIVATION ---")

        def activate():
            cx.activate(persona="engineer")

        bench("PKA activation", activate, 100)

        # ── Summary ──
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"  Semantic write:    {w_sem:.4f}ms")
        print(f"  Episodic write:    {w_epi:.4f}ms")
        print(f"  Working mem write: {w_wm:.4f}ms")
        print(f"  Triple write:      {w_triple:.4f}ms")
        print(f"  Direct read:       {r_get:.4f}ms")
        print(f"  Hybrid recall:     {r_fts:.4f}ms")
        print(f"  Graph query:       {r_graph:.4f}ms")
        print(f"  DB size:           {cx.memory.stats()['db_size_mb']:.2f} MB")
        print(f"  Total memories:    {sum(cx.memory.count().values())}")
        print(f"  Total triples:     {cx.graph.stats()['active_triples']}")
        print("=" * 80)

        cx.close()
    finally:
        os.unlink(db_path)


if __name__ == "__main__":
    main()
