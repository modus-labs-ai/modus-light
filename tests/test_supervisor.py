"""
Tests for Modus Light OTP-pattern Supervisor
"""

import unittest
from modus_light.supervisor import OtpSupervisor
from modus_light.types import ActorSpec
from modus_light.exceptions import ActorCrashError, CircuitBreakerTrippedError


class TestOtpSupervisor(unittest.TestCase):

    def setUp(self):
        self.sup = OtpSupervisor(strategy="one_for_one", max_restarts=3, window_seconds=5.0)

    def test_successful_actor_execution(self):

        def worker(x, y):
            return x + y

        self.sup.register_actor(ActorSpec(name="adder", role="math"), worker)
        res = self.sup.execute_actor("adder", 10, 20)
        self.assertEqual(res, 30)

    def test_unknown_actor_is_rejected(self):
        with self.assertRaises(KeyError):
            self.sup.execute_actor("not_registered")

    def test_transient_crash_is_restarted_in_place(self):
        """A crashing actor is restarted by the supervisor and can recover."""
        attempts = {"count": 0}

        def flaky():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ValueError("Corrupt Input")
            return "recovered"

        self.sup.register_actor(ActorSpec(name="flaky", role="worker"), flaky)
        self.assertEqual(self.sup.execute_actor("flaky"), "recovered")
        self.assertEqual(attempts["count"], 3)
        self.assertEqual(self.sup.get_status()["actors_running"], 1)

    def test_crash_loop_trips_circuit_breaker(self):

        def crash_loop():
            raise RuntimeError("Infinite Crash")

        self.sup.register_actor(
            ActorSpec(name="crasher", role="worker", max_restarts=3, restart_window_seconds=10.0),
            crash_loop
        )

        # The restart budget is exhausted inside a single supervised call
        with self.assertRaises(CircuitBreakerTrippedError):
            self.sup.execute_actor("crasher")

        status = self.sup.get_status()
        self.assertEqual(status["actors_tripped"], 1)
        self.assertEqual(status["status_map"]["crasher"], "TRIPPED")

        # A tripped actor stays out of service
        with self.assertRaises(CircuitBreakerTrippedError):
            self.sup.execute_actor("crasher")

    def test_actor_spec_restart_budget_overrides_the_supervisor_default(self):
        """A per-actor max_restarts must be honored, not silently replaced by the pool default."""
        attempts = {"count": 0}

        def crash_loop():
            attempts["count"] += 1
            raise RuntimeError("Infinite Crash")

        # The supervisor default is 3; this actor is allowed only 1.
        self.sup.register_actor(
            ActorSpec(name="fragile", role="worker", max_restarts=1, restart_window_seconds=10.0),
            crash_loop,
        )

        with self.assertRaises(CircuitBreakerTrippedError):
            self.sup.execute_actor("fragile")

        # 1 initial attempt + 1 permitted restart, then the breaker trips.
        self.assertEqual(attempts["count"], 2)

    def test_temporary_policy_is_never_restarted(self):

        def broken():
            raise RuntimeError("Permanent failure")

        self.sup.register_actor(
            ActorSpec(name="temp", role="worker", restart_policy="temporary"),
            broken
        )
        with self.assertRaises(ActorCrashError):
            self.sup.execute_actor("temp")
        self.assertEqual(self.sup.get_status()["status_map"]["temp"], "FAILED")

    def test_rest_for_one_restarts_dependents(self):
        supervisor = OtpSupervisor(strategy="rest_for_one", max_restarts=3, window_seconds=5.0)
        attempts = {"count": 0}

        def flaky():
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise RuntimeError("transient")
            return "ok"

        supervisor.register_actor(ActorSpec(name="primary", role="db"), flaky)
        supervisor.register_actor(
            ActorSpec(name="dependent", role="cache", depends_on=["primary"]),
            lambda: "ok",
        )
        self.assertEqual(supervisor.execute_actor("primary"), "ok")

        # REST_FOR_ONE also flags the dependent for restart
        self.assertEqual(supervisor.get_status()["status_map"]["dependent"], "RESTARTING")
        # and the dependent runs again normally once it is scheduled
        self.assertEqual(supervisor.execute_actor("dependent"), "ok")
        self.assertEqual(supervisor.get_status()["status_map"]["dependent"], "RUNNING")

    def test_invalid_strategy_is_rejected(self):
        with self.assertRaises(ValueError):
            OtpSupervisor(strategy="whatever")


if __name__ == "__main__":
    unittest.main()
