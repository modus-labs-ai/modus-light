"""
Tests for Modus Light Client & End-to-End Runtime
"""

import os
import unittest
from unittest import mock
from modus_light import ModusLight
from modus_light.exceptions import (
    AuthorizationDeniedError,
    ConfigurationError,
    ReservationCeilingBreachedError,
    SpendCapExceededError,
)


class TestModusLightClient(unittest.TestCase):

    def setUp(self):
        self.rt = ModusLight(tenant_id="test_tenant", spend_cap_tokens=2000)

    def test_shield_and_unshield(self):
        original = "Send wire to user@example.com on 192.0.2.25"
        shielded, tmap = self.rt.shield_prompt(original)
        self.assertNotIn("user@example.com", shielded)
        self.assertNotIn("192.0.2.25", shielded)

        restored = self.rt.unshield_text(shielded, tmap)
        self.assertEqual(restored, original)

    def test_combined_authorization_and_spend_gate(self):
        # Admin with budget
        self.assertTrue(self.rt.authorize_step("admin", "security", 100))

        # Unauthorized role
        with self.assertRaises(AuthorizationDeniedError):
            self.rt.authorize_step("unauthorized_guest", "security", 100)

        # Budget exhaustion
        with self.assertRaises(SpendCapExceededError):
            self.rt.authorize_step("admin", "security", 5000)

    def test_role_named_like_the_sector_is_not_authorized(self):
        """A role must never be authorized just because it shares the sector's
        name: authorization matches whole tuples, not substrings."""
        with self.assertRaises(AuthorizationDeniedError):
            self.rt.authorize_step("security", "security", 100)

    def test_unauthorized_call_does_not_consume_budget(self):
        """Authorization is evaluated before the budget is touched."""
        with self.assertRaises(AuthorizationDeniedError):
            self.rt.authorize_step("attacker", "security", 1500)
        self.assertEqual(self.rt.finops.current_spend, 0)
        self.assertTrue(self.rt.authorize_step("admin", "security", 1500))

    def test_the_documented_path_exposes_a_ceiling_that_excludes_the_prompt(self):
        """The gap worth guarding: `prompt_tokens` existing on the gateway is no
        use if the documented entry point cannot pass it, because then every
        reservation a customer holds reports the whole amount as its output
        budget — prompt plus that amount breaches the ceiling on every call."""
        reservation = self.rt.authorize_step(
            "admin", "cyber_defense", estimated_tokens=1000, prompt_tokens=820
        )
        self.assertEqual(reservation.prompt_tokens, 820)
        self.assertEqual(reservation.max_tokens, 180)
        self.rt.release_reservation(reservation)

    def test_a_step_settling_above_its_ceiling_is_refused_at_the_client(self):
        reservation = self.rt.authorize_step(
            "admin", "cyber_defense", estimated_tokens=100
        )
        with self.assertRaises(ReservationCeilingBreachedError):
            self.rt.commit_spend(900, reservation=reservation)
        # Still catchable by callers written against the general spend error.
        reservation2 = self.rt.authorize_step(
            "admin", "cyber_defense", estimated_tokens=100
        )
        with self.assertRaises(SpendCapExceededError):
            self.rt.commit_spend(900, reservation=reservation2)

    def test_reservation_is_settled_by_commit(self):
        self.rt.authorize_step("admin", "security", 300)
        self.assertEqual(self.rt.finops.current_spend, 300)

        self.rt.commit_spend(250)
        summary = self.rt.finops.get_finops_summary()
        self.assertEqual(summary["consumed_tokens"], 250)
        self.assertEqual(summary["reserved_tokens"], 0)
        self.assertEqual(summary["remaining_tokens"], 1750)

    def test_abandoned_step_releases_its_reservation(self):
        self.rt.authorize_step("admin", "security", 300)
        self.rt.release_reservation()
        self.assertEqual(self.rt.finops.current_spend, 0)

    def test_end_to_end_tuple_workflow(self):
        task = self.rt.submit_task("analyze_log", {"file": "auth.log"}, priority=2)
        self.assertEqual(task.status, "PENDING")

        leased = self.rt.claim_task("worker_node", topic="analyze_log")
        self.assertIsNotNone(leased)
        self.assertEqual(leased.id, task.id)

        self.assertTrue(self.rt.complete_task(leased.id, {"anomalies_detected": 0}, worker_id="worker_node"))

    def test_complete_task_enforces_lease_ownership_through_the_facade(self):
        """The exclusive-lease guarantee must hold at the documented API, not just internally."""
        self.rt.submit_task("analyze_log", {"file": "auth.log"})
        leased = self.rt.claim_task("worker_a", topic="analyze_log")
        self.assertIsNotNone(leased)

        # A worker that never held the lease is refused.
        self.assertFalse(self.rt.complete_task(leased.id, {"ok": True}, worker_id="worker_b"))
        self.assertEqual(leased.status, "LEASED")

        # The holder succeeds.
        self.assertTrue(self.rt.complete_task(leased.id, {"ok": True}, worker_id="worker_a"))
        self.assertEqual(leased.status, "COMPLETED")

    def test_complete_task_rejects_a_tuple_nobody_claimed(self):
        task = self.rt.submit_task("analyze_log", {"file": "auth.log"})
        self.assertFalse(self.rt.complete_task(task.id, {"ok": True}, worker_id="nobody"))

    def test_smoke_audit(self):
        report = self.rt.run_smoke_audit()
        self.assertEqual(report.checks_total, 16)
        self.assertEqual(report.checks_passed, report.checks_total)
        self.assertEqual(report.checks_failed, 0)
        self.assertEqual(report.status, "PASSED")
        self.assertEqual(report.findings, [])
        self.assertEqual(report.symlink_count, 0)

    def test_smoke_audit_reports_failures_instead_of_always_passing(self):
        """A broken check must surface as a FAILED report with a finding."""

        def broken_check():
            raise AssertionError("simulated failure")

        self.rt._audit_finops_refusal = broken_check
        report = self.rt.run_smoke_audit()
        self.assertEqual(report.status, "FAILED")
        self.assertEqual(report.checks_failed, 1)
        self.assertEqual(len(report.findings), 1)
        self.assertIn("finops_over_cap_refusal", report.findings[0])

    def test_runtime_is_network_free(self):
        self.assertTrue(self.rt.network_free())
        self.assertTrue(self.rt.check_health()["air_gap_compliant"])

    def test_spend_cap_is_read_from_the_environment(self):
        """A documented environment variable must actually configure the
        runtime, or the operator's spend ceiling is silently ignored."""
        with mock.patch.dict(os.environ, {"MODUS_SPEND_CAP_TOKENS": "1234", "MODUS_TENANT_ID": "acme"}):
            rt = ModusLight()
        self.assertEqual(rt.finops.spend_cap_tokens, 1234)
        self.assertEqual(rt.tenant_id, "acme")

    def test_explicit_arguments_beat_the_environment(self):
        with mock.patch.dict(os.environ, {"MODUS_SPEND_CAP_TOKENS": "1234", "MODUS_TENANT_ID": "acme"}):
            rt = ModusLight(tenant_id="explicit", spend_cap_tokens=99)
        self.assertEqual(rt.finops.spend_cap_tokens, 99)
        self.assertEqual(rt.tenant_id, "explicit")

    def test_malformed_spend_cap_fails_loudly(self):
        """A kill switch must never silently guess its own ceiling."""
        with mock.patch.dict(os.environ, {"MODUS_SPEND_CAP_TOKENS": "lots"}):
            with self.assertRaises(ConfigurationError):
                ModusLight()

    def test_blank_spend_cap_falls_back_to_the_default(self):
        with mock.patch.dict(os.environ, {"MODUS_SPEND_CAP_TOKENS": "  "}):
            rt = ModusLight()
        self.assertEqual(rt.finops.spend_cap_tokens, ModusLight.DEFAULT_SPEND_CAP_TOKENS)


if __name__ == "__main__":
    unittest.main()
