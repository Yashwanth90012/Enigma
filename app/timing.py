"""Performance Instrumentation, Correlation IDs, and Latency Metrics Tracker for ENIGMA / EQUILIBRA.

Provides zero-dependency, thread-safe, high-precision latency profiling across:
- FastAPI HTTP Request-Response Lifecycles
- NVIDIA NIM Inference & Time-to-First-Token
- Database Query Processing & Connection Acquisition
- Neural Embeddings & Vector Search
- Multi-Agent Orchestration Pipelines
"""

import time
import math
import uuid
import logging
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Dict, Any, List, Optional

logger = logging.getLogger("equilibra.performance")


class PerformanceMetricsTracker:
    """Thread-safe in-memory performance telemetry tracking percentiles (P50, P95, P99),

    request counts, error rates, and stage breakdowns.
    """

    def __init__(self, max_history: int = 500):
        self._max_history = max_history
        self._latencies: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self._max_history))
        self._error_counts: Dict[str, int] = defaultdict(int)
        self._total_counts: Dict[str, int] = defaultdict(int)
        self._cache_hits: int = 0
        self._cache_misses: int = 0

    def record_latency(self, stage: str, duration_ms: float, is_error: bool = False):
        self._latencies[stage].append(duration_ms)
        self._total_counts[stage] += 1
        if is_error:
            self._error_counts[stage] += 1

    def record_cache_event(self, hit: bool):
        if hit:
            self._cache_hits += 1
        else:
            self._cache_misses += 1

    @contextmanager
    def time_stage(self, stage: str, extra_tags: Optional[Dict[str, Any]] = None):
        """Context manager to measure execution duration of a stage with automatic error recording."""
        start = time.perf_counter()
        is_err = False
        try:
            yield
        except Exception:
            is_err = True
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.record_latency(stage, elapsed_ms, is_error=is_err)
            if extra_tags:
                logger.debug("Stage '%s' completed in %.2fms %s", stage, elapsed_ms, extra_tags)

    def get_stage_stats(self, stage: str) -> Dict[str, Any]:
        samples = list(self._latencies.get(stage, []))
        total = self._total_counts.get(stage, 0)
        errors = self._error_counts.get(stage, 0)
        if not samples:
            return {
                "count": total,
                "errors": errors,
                "error_rate_pct": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "avg_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0
            }

        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        p50 = sorted_samples[int(math.floor(0.50 * (n - 1)))]
        p95 = sorted_samples[int(math.floor(0.95 * (n - 1)))]
        p99 = sorted_samples[int(math.floor(0.99 * (n - 1)))]
        avg = round(sum(sorted_samples) / n, 2)
        error_rate = round((errors / max(1, total)) * 100, 2)

        return {
            "count": total,
            "sample_size": n,
            "errors": errors,
            "error_rate_pct": error_rate,
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "avg_ms": avg,
            "min_ms": round(sorted_samples[0], 2),
            "max_ms": round(sorted_samples[-1], 2)
        }

    def get_summary(self) -> Dict[str, Any]:
        total_cache = self._cache_hits + self._cache_misses
        hit_ratio = round((self._cache_hits / max(1, total_cache)) * 100, 1)

        summary = {
            "timestamp": time.time(),
            "cache_stats": {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "hit_ratio_pct": hit_ratio
            },
            "stages": {}
        }
        for st in list(self._total_counts.keys()):
            summary["stages"][st] = self.get_stage_stats(st)
        return summary

    def reset(self):
        self._latencies.clear()
        self._error_counts.clear()
        self._total_counts.clear()
        self._cache_hits = 0
        self._cache_misses = 0


# Global singleton metrics tracker
perf_tracker = PerformanceMetricsTracker()
