"""
Swarm Orchestrator for Sigil.
DAG-based task execution with model routing, circuit breakers,
budget awareness, and memory-informed routing.
"""

import json
import time
import uuid
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Callable
from collections import defaultdict


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ModelTier(str, Enum):
    LIGHT = "light"    # Mini/Flash — trivial tasks
    MID = "mid"        # Sonnet/Pro — moderate tasks
    HEAVY = "heavy"    # Opus — complex tasks


@dataclass
class Task:
    id: str
    prompt: str
    depends_on: list[str] = field(default_factory=list)
    model_tier: str = "auto"
    executor: str = "default"
    timeout_seconds: int = 300
    priority: int = 0
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    error: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    cost_estimate: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class SwarmResult:
    tasks: list[Task]
    total_time_seconds: float = 0.0
    total_cost_estimate: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    skipped_count: int = 0


class CircuitBreaker:
    """Per-executor circuit breaker to prevent cascading failures."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: int = 60):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._open_until: dict[str, float] = {}

    def record_failure(self, executor: str):
        now = time.time()
        self._failures[executor].append(now)
        # Clean old failures
        cutoff = now - self.cooldown_seconds
        self._failures[executor] = [t for t in self._failures[executor] if t > cutoff]
        if len(self._failures[executor]) >= self.failure_threshold:
            self._open_until[executor] = now + self.cooldown_seconds

    def record_success(self, executor: str):
        self._failures[executor] = []
        self._open_until.pop(executor, None)

    def is_open(self, executor: str) -> bool:
        if executor not in self._open_until:
            return False
        if time.time() > self._open_until[executor]:
            del self._open_until[executor]
            return False
        return True


class ComplexityEstimator:
    """
    9-signal complexity estimator (inspired by Zouroboros OmniRoute).
    Determines optimal model tier for a task.
    """

    WEIGHTS = {
        "concept_count": 0.20,
        "feature_list_count": 0.20,
        "scope_breadth": 0.12,
        "multi_step": 0.10,
        "verb_complexity": 0.10,
        "analysis_depth": 0.08,
        "word_count": 0.08,
        "tool_usage": 0.06,
        "file_refs": 0.06,
    }

    COMPLEX_VERBS = {
        "architect", "design", "implement", "refactor", "optimize",
        "migrate", "integrate", "orchestrate", "synthesize", "analyze",
        "debug", "diagnose", "evaluate", "benchmark", "audit"
    }

    SIMPLE_VERBS = {
        "list", "show", "get", "find", "check", "count", "read",
        "print", "display", "summarize", "format", "convert"
    }

    def estimate(self, prompt: str) -> tuple[ModelTier, float]:
        """Return (tier, complexity_score) for a prompt."""
        words = prompt.lower().split()
        signals = {
            "concept_count": self._concept_count(words),
            "feature_list_count": self._feature_list_count(prompt),
            "scope_breadth": self._scope_breadth(words),
            "multi_step": self._multi_step(prompt),
            "verb_complexity": self._verb_complexity(words),
            "analysis_depth": self._analysis_depth(words),
            "word_count": min(len(words) / 200, 1.0),
            "tool_usage": self._tool_usage(prompt),
            "file_refs": self._file_refs(prompt),
        }

        score = sum(signals[k] * self.WEIGHTS[k] for k in self.WEIGHTS)
        score = max(0.0, min(1.0, score))

        if score < 0.25:
            return ModelTier.LIGHT, score
        elif score < 0.6:
            return ModelTier.MID, score
        else:
            return ModelTier.HEAVY, score

    def _concept_count(self, words: list[str]) -> float:
        tech_terms = {"api", "database", "auth", "oauth", "jwt", "graphql",
                      "rest", "websocket", "cache", "queue", "worker",
                      "migration", "schema", "index", "deployment",
                      "container", "kubernetes", "docker", "ci/cd",
                      "pipeline", "microservice", "monolith", "vector",
                      "embedding", "llm", "rag", "agent", "swarm"}
        found = sum(1 for w in words if w in tech_terms)
        return min(found / 5, 1.0)

    def _feature_list_count(self, prompt: str) -> float:
        indicators = prompt.count("\n-") + prompt.count("\n*") + prompt.count("\n1.")
        return min(indicators / 5, 1.0)

    def _scope_breadth(self, words: list[str]) -> float:
        scope_words = {"across", "all", "every", "entire", "full",
                       "comprehensive", "end-to-end", "system-wide"}
        return min(sum(1 for w in words if w in scope_words) / 2, 1.0)

    def _multi_step(self, prompt: str) -> float:
        step_indicators = ["then", "after that", "next", "finally",
                           "step 1", "step 2", "first", "second"]
        found = sum(1 for s in step_indicators if s in prompt.lower())
        return min(found / 3, 1.0)

    def _verb_complexity(self, words: list[str]) -> float:
        complex_found = sum(1 for w in words if w in self.COMPLEX_VERBS)
        simple_found = sum(1 for w in words if w in self.SIMPLE_VERBS)
        if complex_found + simple_found == 0:
            return 0.5
        return complex_found / (complex_found + simple_found)

    def _analysis_depth(self, words: list[str]) -> float:
        depth_words = {"why", "how", "compare", "tradeoff", "trade-off",
                       "pros", "cons", "evaluate", "versus", "vs"}
        return min(sum(1 for w in words if w in depth_words) / 2, 1.0)

    def _tool_usage(self, prompt: str) -> float:
        tool_indicators = ["run", "execute", "call", "invoke", "use tool",
                           "api call", "query", "fetch"]
        found = sum(1 for t in tool_indicators if t in prompt.lower())
        return min(found / 3, 1.0)

    def _file_refs(self, prompt: str) -> float:
        import re
        paths = re.findall(r'[/\\][\w./-]+\.\w+', prompt)
        return min(len(paths) / 3, 1.0)


class SwarmOrchestrator:
    """
    DAG-based swarm orchestrator with model routing and circuit breakers.
    """

    def __init__(self, memory_engine=None, max_concurrent: int = 8,
                 budget_limit: float = 10.0):
        self.memory = memory_engine
        self.max_concurrent = max_concurrent
        self.budget_limit = budget_limit
        self.circuit_breaker = CircuitBreaker()
        self.complexity = ComplexityEstimator()
        self._executors: dict[str, Callable] = {}
        self._execution_history: list[dict] = []

    def register_executor(self, name: str, fn: Callable[[str, str], str]):
        """
        Register an executor function.
        fn(prompt, model_tier) -> result_text
        """
        self._executors[name] = fn

    def orchestrate(self, tasks: list[dict],
                    cascade_policy: str = "skip_dependents") -> SwarmResult:
        """
        Execute a DAG of tasks.

        cascade_policy: what to do when a task fails
            - 'abort_dependents': skip all downstream tasks
            - 'skip_dependents': skip direct dependents only
            - 'retry_then_skip': retry once, then skip
            - 'continue': ignore failure, continue
        """
        start_time = time.time()

        # Parse tasks
        task_map: dict[str, Task] = {}
        for t in tasks:
            task = Task(
                id=t.get("id", f"task_{uuid.uuid4().hex[:8]}"),
                prompt=t.get("prompt", ""),
                depends_on=t.get("depends_on", []),
                model_tier=t.get("model_tier", "auto"),
                executor=t.get("executor", "default"),
                timeout_seconds=t.get("timeout", 300),
                priority=t.get("priority", 0),
                metadata=t.get("metadata", {}),
            )
            task_map[task.id] = task

        # Validate DAG (no cycles)
        if self._has_cycle(task_map):
            raise ValueError("Task graph has a cycle")

        # Execute in topological order
        completed = set()
        failed = set()
        total_cost = 0.0

        while True:
            # Find ready tasks (all deps satisfied)
            ready = [
                t for t in task_map.values()
                if t.status == TaskStatus.PENDING
                and all(d in completed for d in t.depends_on)
                and (cascade_policy == "continue"
                     or not any(d in failed for d in t.depends_on))
            ]

            # Skip tasks whose dependencies failed
            if cascade_policy in ("abort_dependents", "skip_dependents"):
                for t in task_map.values():
                    if t.status == TaskStatus.PENDING and any(d in failed for d in t.depends_on):
                        t.status = TaskStatus.SKIPPED
                        t.error = "Dependency failed"

            if not ready:
                break  # All done or deadlocked

            # Sort by priority
            ready.sort(key=lambda x: x.priority, reverse=True)

            # Execute batch (up to max_concurrent)
            batch = ready[:self.max_concurrent]
            for task in batch:
                self._execute_task(task, task_map, total_cost)
                if task.status == TaskStatus.COMPLETED:
                    completed.add(task.id)
                    total_cost += task.cost_estimate
                elif task.status == TaskStatus.FAILED:
                    failed.add(task.id)

                    # Retry once if policy says so
                    if cascade_policy == "retry_then_skip":
                        task.status = TaskStatus.PENDING
                        task.error = ""
                        self._execute_task(task, task_map, total_cost)
                        if task.status == TaskStatus.COMPLETED:
                            completed.add(task.id)
                            failed.discard(task.id)
                            total_cost += task.cost_estimate

            # Budget check
            if total_cost > self.budget_limit:
                for t in task_map.values():
                    if t.status == TaskStatus.PENDING:
                        t.status = TaskStatus.SKIPPED
                        t.error = f"Budget exceeded (${total_cost:.2f}/${self.budget_limit:.2f})"
                break

        elapsed = time.time() - start_time
        all_tasks = list(task_map.values())

        result = SwarmResult(
            tasks=all_tasks,
            total_time_seconds=round(elapsed, 2),
            total_cost_estimate=round(total_cost, 4),
            success_count=sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED),
            failure_count=sum(1 for t in all_tasks if t.status == TaskStatus.FAILED),
            skipped_count=sum(1 for t in all_tasks if t.status == TaskStatus.SKIPPED),
        )

        # Record to execution history
        self._execution_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tasks": len(all_tasks),
            "success": result.success_count,
            "failed": result.failure_count,
            "time": result.total_time_seconds,
            "cost": result.total_cost_estimate,
        })

        # Save as episodic memory if memory engine available
        if self.memory:
            summary = (f"Swarm run: {result.success_count}/{len(all_tasks)} tasks completed "
                       f"in {result.total_time_seconds}s, ${result.total_cost_estimate}")
            self.memory.remember_episodic(
                summary=summary,
                outcome="success" if result.failure_count == 0 else "partial",
                importance=0.6,
                source="orchestrator",
                tags=["swarm", "orchestration"]
            )

        return result

    def _execute_task(self, task: Task, task_map: dict[str, Task],
                      current_cost: float):
        """Execute a single task."""
        now = datetime.now(timezone.utc).isoformat()
        task.started_at = now
        task.status = TaskStatus.RUNNING

        # Determine model tier
        if task.model_tier == "auto":
            tier, complexity_score = self.complexity.estimate(task.prompt)
            task.model_tier = tier.value
            task.metadata["complexity_score"] = round(complexity_score, 3)
        else:
            tier = ModelTier(task.model_tier)

        # Budget-aware downgrade
        remaining_budget = self.budget_limit - current_cost
        if remaining_budget < self.budget_limit * 0.2:
            tier = ModelTier.LIGHT
            task.model_tier = tier.value
            task.metadata["budget_downgraded"] = True

        # Circuit breaker check
        executor_name = task.executor
        if self.circuit_breaker.is_open(executor_name):
            # Try fallback executor
            fallback = self._get_fallback(executor_name)
            if fallback and not self.circuit_breaker.is_open(fallback):
                executor_name = fallback
                task.metadata["fallback_executor"] = executor_name
            else:
                task.status = TaskStatus.FAILED
                task.error = f"Circuit breaker open for {executor_name}"
                return

        # Build context from dependency results
        context_parts = []
        for dep_id in task.depends_on:
            dep_task = task_map.get(dep_id)
            if dep_task and dep_task.result:
                context_parts.append(f"[Result from {dep_id}]: {dep_task.result[:2000]}")

        full_prompt = task.prompt
        if context_parts:
            full_prompt = "\n".join(context_parts) + "\n\n" + task.prompt

        # Execute
        executor_fn = self._executors.get(executor_name)
        if not executor_fn:
            task.status = TaskStatus.FAILED
            task.error = f"No executor registered: {executor_name}"
            return

        try:
            result = executor_fn(full_prompt, task.model_tier)
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.cost_estimate = self._estimate_cost(full_prompt, result, tier)
            self.circuit_breaker.record_success(executor_name)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            self.circuit_breaker.record_failure(executor_name)

        task.completed_at = datetime.now(timezone.utc).isoformat()

    def _estimate_cost(self, prompt: str, result: str, tier: ModelTier) -> float:
        """Rough cost estimate based on token count and tier."""
        input_tokens = len(prompt) / 4
        output_tokens = len(result) / 4

        # Approximate cost per 1M tokens
        costs = {
            ModelTier.LIGHT: {"input": 0.25, "output": 1.0},
            ModelTier.MID: {"input": 3.0, "output": 15.0},
            ModelTier.HEAVY: {"input": 15.0, "output": 75.0},
        }
        tier_cost = costs.get(tier, costs[ModelTier.MID])
        return (input_tokens * tier_cost["input"] + output_tokens * tier_cost["output"]) / 1_000_000

    def _get_fallback(self, executor: str) -> Optional[str]:
        """Get fallback executor."""
        fallbacks = {k: k for k in self._executors if k != executor}
        return next(iter(fallbacks), None)

    def _has_cycle(self, task_map: dict[str, Task]) -> bool:
        """Detect cycles in the task DAG."""
        visited = set()
        rec_stack = set()

        def dfs(task_id):
            visited.add(task_id)
            rec_stack.add(task_id)
            task = task_map.get(task_id)
            if task:
                for dep in task.depends_on:
                    if dep not in visited:
                        if dfs(dep):
                            return True
                    elif dep in rec_stack:
                        return True
            rec_stack.discard(task_id)
            return False

        for tid in task_map:
            if tid not in visited:
                if dfs(tid):
                    return True
        return False

    def stats(self) -> dict:
        """Orchestration statistics."""
        if not self._execution_history:
            return {"runs": 0}
        total_runs = len(self._execution_history)
        total_tasks = sum(h["tasks"] for h in self._execution_history)
        total_success = sum(h["success"] for h in self._execution_history)
        avg_time = sum(h["time"] for h in self._execution_history) / total_runs
        total_cost = sum(h["cost"] for h in self._execution_history)

        return {
            "runs": total_runs,
            "total_tasks": total_tasks,
            "total_success": total_success,
            "success_rate": round(total_success / max(1, total_tasks), 3),
            "avg_time_seconds": round(avg_time, 2),
            "total_cost": round(total_cost, 4),
        }
