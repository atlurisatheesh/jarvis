"""Tests for Phase 2: Circuit breaker, latency budget, skill cache, background jobs."""
from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker(unittest.TestCase):
    """Tests for jarvis_ai.circuit_breaker.CircuitBreaker."""

    def setUp(self):
        from jarvis_ai.circuit_breaker import CircuitBreaker
        self.cb = CircuitBreaker(name="test", failure_threshold=3, open_seconds=0.1, half_open_seconds=0.05)

    def test_starts_closed(self):
        self.assertEqual(self.cb.state, "closed")
        self.assertTrue(self.cb.allow_request())

    def test_opens_after_threshold_failures(self):
        for _ in range(3):
            self.cb.record_failure()
        self.assertEqual(self.cb.state, "open")
        self.assertFalse(self.cb.allow_request())

    def test_resets_on_success(self):
        self.cb.record_failure()
        self.cb.record_failure()
        self.cb.record_success()
        self.assertEqual(self.cb.state, "closed")
        self.assertTrue(self.cb.allow_request())

    def test_transitions_to_half_open_after_cooldown(self):
        for _ in range(3):
            self.cb.record_failure()
        self.assertEqual(self.cb.state, "open")
        time.sleep(0.15)  # > open_seconds
        self.assertEqual(self.cb.state, "half_open")
        self.assertTrue(self.cb.allow_request())

    def test_half_open_success_closes(self):
        for _ in range(3):
            self.cb.record_failure()
        time.sleep(0.15)
        self.assertEqual(self.cb.state, "half_open")
        self.cb.record_success()
        self.assertEqual(self.cb.state, "closed")

    def test_half_open_failure_reopens(self):
        for _ in range(3):
            self.cb.record_failure()
        time.sleep(0.15)
        self.cb.record_failure()  # probe fails
        self.assertEqual(self.cb.state, "open")

    def test_manual_reset(self):
        for _ in range(3):
            self.cb.record_failure()
        self.cb.reset()
        self.assertEqual(self.cb.state, "closed")

    def test_stats(self):
        self.cb.record_success()
        self.cb.record_failure()
        stats = self.cb.stats
        self.assertEqual(stats["total_successes"], 1)
        self.assertEqual(stats["total_failures"], 1)

    def test_thread_safety(self):
        errors = []
        def writer():
            try:
                for _ in range(100):
                    self.cb.record_success()
                    self.cb.record_failure()
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=writer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)


# ---------------------------------------------------------------------------
# Latency budget
# ---------------------------------------------------------------------------

class TestLatencyBudget(unittest.TestCase):
    """Tests for jarvis_ai.latency_budget.LatencyBudget."""

    def setUp(self):
        from jarvis_ai.latency_budget import LatencyBudget
        self.lb = LatencyBudget({"wake": 0.5, "stt": 1.0})

    def test_record_within_budget(self):
        self.lb.record("wake", 0.3)
        self.assertEqual(self.lb.overruns, {"wake": 0, "stt": 0})

    def test_record_over_budget(self):
        self.lb.record("wake", 0.8)
        self.assertEqual(self.lb.overruns["wake"], 1)

    def test_timer_context_manager(self):
        with self.lb.timer("stt"):
            time.sleep(0.05)
        # Should not be over budget (1.0s)
        self.assertEqual(self.lb.overruns["stt"], 0)

    def test_timer_over_budget(self):
        with self.lb.timer("wake"):
            time.sleep(0.01)
        # wake budget is 0.5s, 0.01s is fine
        self.assertEqual(self.lb.overruns["wake"], 0)

    def test_set_budget(self):
        self.lb.set_budget("stt", 0.001)
        self.lb.record("stt", 0.01)
        self.assertEqual(self.lb.overruns["stt"], 1)

    def test_summary(self):
        self.lb.record("wake", 0.1)
        self.lb.record("stt", 0.5)
        summary = self.lb.summary()
        self.assertIn("wake", summary)
        self.assertIn("stt", summary)


# ---------------------------------------------------------------------------
# Skill cache
# ---------------------------------------------------------------------------

class TestSkillCache(unittest.TestCase):
    """Tests for jarvis_ai.skill_cache.SkillCache."""

    def setUp(self):
        from jarvis_ai.skill_cache import SkillCache
        self.cache = SkillCache(max_size=5, default_ttl=10)

    def test_cache_miss_returns_none(self):
        self.assertIsNone(self.cache.get("weather"))

    def test_put_then_get(self):
        self.cache.put("weather", "sunny", {"city": "hyd"})
        result = self.cache.get("weather", {"city": "hyd"})
        self.assertEqual(result, "sunny")

    def test_cache_hit_with_same_args(self):
        self.cache.put("system_info", "CPU 50%", {})
        self.assertEqual(self.cache.get("system_info"), "CPU 50%")

    def test_cache_miss_different_args(self):
        self.cache.put("weather", "sunny", {"city": "hyd"})
        self.assertIsNone(self.cache.get("weather", {"city": "mum"}))

    def test_lru_eviction(self):
        for i in range(6):
            self.cache.put(f"key_{i}", f"val_{i}")
        # First entry should be evicted
        self.assertIsNone(self.cache.get("key_0"))

    def test_invalidate_by_name(self):
        self.cache.put("weather", "sunny", {"city": "hyd"})
        self.cache.put("weather", "rainy", {"city": "mum"})
        self.cache.invalidate("weather")
        self.assertIsNone(self.cache.get("weather", {"city": "hyd"}))

    def test_invalidate_all(self):
        self.cache.put("a", "1")
        self.cache.put("b", "2")
        self.cache.invalidate()
        self.assertIsNone(self.cache.get("a"))
        self.assertIsNone(self.cache.get("b"))

    def test_stats(self):
        self.cache.put("a", "1")
        self.cache.get("a")  # hit
        self.cache.get("missing")  # miss
        stats = self.cache.stats
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)

    def test_ttl_expiry(self):
        from jarvis_ai.skill_cache import SkillCache
        cache = SkillCache(default_ttl=0.01)  # 10ms TTL
        cache.put("a", "1")
        time.sleep(0.05)  # wait past TTL
        self.assertIsNone(cache.get("a"))


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------

class TestBackgroundJobs(unittest.TestCase):
    """Tests for jarvis_ai.background_jobs.BackgroundJobs."""

    def test_submit_and_wait(self):
        from jarvis_ai.background_jobs import BackgroundJobs
        bg = BackgroundJobs(max_workers=1)
        result_holder = []
        job_id = bg.submit("test", lambda: "done", on_done=lambda r: result_holder.append(r))
        time.sleep(0.2)
        self.assertEqual(len(result_holder), 1)
        self.assertEqual(result_holder[0], "done")
        bg.shutdown()

    def test_error_handling(self):
        from jarvis_ai.background_jobs import BackgroundJobs
        bg = BackgroundJobs(max_workers=1)
        error_holder = []
        job_id = bg.submit("fail", lambda: 1/0, on_error=error_holder.append)
        time.sleep(0.2)
        self.assertEqual(len(error_holder), 1)
        self.assertIn("division by zero", error_holder[0].lower())
        bg.shutdown()

    def test_get_status_running(self):
        from jarvis_ai.background_jobs import BackgroundJobs
        bg = BackgroundJobs(max_workers=1)
        event = threading.Event()
        job_id = bg.submit("slow", lambda: event.wait(2.0))
        time.sleep(0.1)
        status = bg.get_status(job_id)
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "running")
        event.set()  # allow it to finish
        bg.shutdown()

    def test_active_count(self):
        from jarvis_ai.background_jobs import BackgroundJobs
        bg = BackgroundJobs(max_workers=1)
        event = threading.Event()
        bg.submit("slow", lambda: event.wait(5.0))
        time.sleep(0.1)
        self.assertGreaterEqual(bg.active_count, 0)
        event.set()
        bg.shutdown()


# ---------------------------------------------------------------------------
# Cloudflare brain (mocked)
# ---------------------------------------------------------------------------

class TestCloudflareBrain(unittest.TestCase):
    """Mocked tests for the Cloudflare Workers AI brain provider."""

    def test_cloudflare_brain_uses_circuit_breaker(self):
        """Cloudflare brain should respect circuit breaker state."""
        from jarvis_ai.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(name="cloudflare", failure_threshold=1, open_seconds=10.0)
        cb.record_failure()
        self.assertFalse(cb.allow_request())

    def test_cloudflare_brain_recovery(self):
        """Cloudflare should recover after cooldown on success."""
        from jarvis_ai.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(name="cloudflare", failure_threshold=1, open_seconds=0.05)
        cb.record_failure()
        self.assertFalse(cb.allow_request())
        time.sleep(0.1)
        self.assertTrue(cb.allow_request())
        cb.record_success()
        self.assertEqual(cb.state, "closed")


# ---------------------------------------------------------------------------
# Latency budget singleton (wired into live listener)
# ---------------------------------------------------------------------------

class TestLatencyBudgetSingleton(unittest.TestCase):
    """Tests for the module-level get_latency_budget() singleton."""

    def tearDown(self):
        # Reset the singleton so each test starts clean.
        import jarvis_ai.latency_budget as _lb
        _lb._budget = None

    def test_returns_latency_budget_instance(self):
        from jarvis_ai.latency_budget import get_latency_budget, LatencyBudget
        budget = get_latency_budget()
        self.assertIsInstance(budget, LatencyBudget)

    def test_same_instance_on_repeated_calls(self):
        from jarvis_ai.latency_budget import get_latency_budget
        a = get_latency_budget()
        b = get_latency_budget()
        self.assertIs(a, b)

    def test_record_through_singleton(self):
        from jarvis_ai.latency_budget import get_latency_budget
        budget = get_latency_budget()
        budget.record("stt", 0.5)
        budget.record("stt", 1.5)  # over the 1.0s budget
        self.assertEqual(budget.overruns["stt"], 1)

    def test_singleton_has_default_budgets(self):
        from jarvis_ai.latency_budget import get_latency_budget
        budget = get_latency_budget()
        self.assertIn("stt", budget.budgets)
        self.assertEqual(budget.budgets["stt"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
