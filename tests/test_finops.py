"""
Tests for Modus Light FinOps Gateway
"""

import unittest
from modus_light.finops import FinOpsGateway
from modus_light.types import ModelTier
from modus_light.exceptions import SpendCapExceededError


class TestFinOpsGateway(unittest.TestCase):

    def setUp(self):
        self.gateway = FinOpsGateway(spend_cap_tokens=1000)

    def test_pre_dispatch_check_within_budget(self):
        self.assertTrue(self.gateway.pre_dispatch_check(500))

    def test_pre_dispatch_check_exceeds_budget(self):
        with self.assertRaises(SpendCapExceededError):
            self.gateway.pre_dispatch_check(1500)

    def test_pre_dispatch_check_does_not_consume_budget(self):
        self.gateway.pre_dispatch_check(500)
        self.assertEqual(self.gateway.current_spend, 0)

    def test_spend_accumulation_and_kill_switch(self):
        self.gateway.commit_spend(actual_tokens=800, tokens_saved=2000)
        self.assertEqual(self.gateway.remaining_budget, 200)

        # 150 tokens should pass
        self.assertTrue(self.gateway.pre_dispatch_check(150))

        # 300 tokens should trip kill switch
        with self.assertRaises(SpendCapExceededError):
            self.gateway.pre_dispatch_check(300)

    def test_reservation_holds_budget_until_settled(self):
        reservation = self.gateway.reserve(300)
        self.assertEqual(self.gateway.remaining_budget, 700)
        self.assertEqual(self.gateway.current_spend, 300)

        self.gateway.commit_spend(250, reservation=reservation)
        summary = self.gateway.get_finops_summary()
        self.assertEqual(summary["consumed_tokens"], 250)
        self.assertEqual(summary["reserved_tokens"], 0)
        self.assertEqual(summary["remaining_tokens"], 750)

    def test_release_returns_budget(self):
        reservation = self.gateway.reserve(300)
        self.gateway.release(reservation)
        self.assertEqual(self.gateway.current_spend, 0)
        self.assertEqual(self.gateway.remaining_budget, 1000)

    def test_reservation_over_cap_is_refused(self):
        with self.assertRaises(SpendCapExceededError):
            self.gateway.reserve(1500)
        self.assertEqual(self.gateway.current_spend, 0)

    def test_no_overdraft_while_every_step_costs_what_it_estimated(self):
        """A refused step spends nothing, so the reported overdraft stays zero."""
        with self.assertRaises(SpendCapExceededError):
            self.gateway.reserve(1500)
        self.assertEqual(self.gateway.get_finops_summary()["overdraft_amount"], 0.0)

    def test_settling_above_the_granted_ceiling_is_refused(self):
        """The reservation is a hard ceiling, which is what makes the overdraft
        bound real rather than a prediction a caller may ignore."""
        reservation = self.gateway.reserve(100, tier=ModelTier.PRO)
        with self.assertRaises(SpendCapExceededError):
            self.gateway.commit_spend(400, reservation=reservation)

        summary = self.gateway.get_finops_summary()
        # The spend is still recorded truthfully: the tokens were really consumed.
        self.assertEqual(summary["consumed_tokens"], 400)
        self.assertEqual(summary["ceiling_breaches"], 1)

    def test_a_step_within_its_ceiling_leaves_no_breach_and_no_overdraft(self):
        reservation = self.gateway.reserve(300, tier=ModelTier.FLASH)
        self.gateway.commit_spend(250, reservation=reservation)
        summary = self.gateway.get_finops_summary()
        self.assertEqual(summary["ceiling_breaches"], 0)
        self.assertEqual(summary["overdraft_amount"], 0.0)
        self.assertEqual(summary["overdraft_tokens"], 0)

    def test_the_ceiling_is_exposed_for_the_provider_call(self):
        """`max_tokens` is how the ceiling binds the provider rather than the
        caller's good intentions."""
        reservation = self.gateway.reserve(275)
        self.assertEqual(reservation.max_tokens, 275)

    def test_overdraft_is_measured_when_enforcement_is_disabled(self):
        """With the ceiling off, an overrun must still be visible in telemetry —
        a hard-coded zero would report a balanced budget at the one moment it
        matters."""
        lax = FinOpsGateway(spend_cap_tokens=1000, enforce_reservation_ceiling=False)
        reservation = lax.reserve(100, tier=ModelTier.PRO)
        lax.commit_spend(1400, reservation=reservation)

        summary = lax.get_finops_summary()
        self.assertEqual(summary["overdraft_tokens"], 400)
        self.assertGreater(summary["overdraft_amount"], 0.0)

    def test_tier_arbitrage_recommendation(self):
        self.assertEqual(self.gateway.recommend_tier(200), ModelTier.FLASH_LITE)
        self.assertEqual(self.gateway.recommend_tier(1500), ModelTier.FLASH)
        self.assertEqual(self.gateway.recommend_tier(5000), ModelTier.PRO)
        self.assertEqual(self.gateway.recommend_tier(300, requires_deep_planning=True), ModelTier.PRO)


if __name__ == "__main__":
    unittest.main()
