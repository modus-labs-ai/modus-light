"""
Tests for Modus Light Google Zanzibar ReBAC
"""

import threading
import unittest
from modus_light.rebac import ZanzibarReBAC
from modus_light.types import AttenuationLevel
from modus_light.exceptions import AuthorizationDeniedError


class TestZanzibarReBAC(unittest.TestCase):

    def setUp(self):
        self.rebac = ZanzibarReBAC()

    def test_direct_and_wildcard_relation(self):
        self.rebac.add_relation("bob", "read", "financial_records")
        self.assertTrue(self.rebac.check("bob", "read", "financial_records"))
        self.assertFalse(self.rebac.check("bob", "write", "financial_records"))

        # Admin wildcard
        self.assertTrue(self.rebac.check("admin", "can_execute", "any_service"))

    def test_transitive_group_membership(self):
        self.rebac.add_relation("analyst_1", "member_of", "audit_team")
        self.rebac.add_relation("audit_team", "access", "ledger_db")
        self.assertTrue(self.rebac.check("analyst_1", "access", "ledger_db"))

    def test_confused_deputy_defense(self):
        # Ensure substring matches do not leak authorization
        self.rebac.add_relation("super_admin", "execute", "root_vault")
        self.assertFalse(self.rebac.check("super_admin_fake", "execute", "root_vault"))
        self.assertFalse(self.rebac.check("fake_super_admin", "execute", "root_vault"))

    def test_monotonic_privilege_attenuation(self):
        self.rebac.add_relation("worker", "process", "queue")
        # Worker can be authorized at L2
        self.assertTrue(self.rebac.authorize(
            subject="worker",
            relation="process",
            object_resource="queue",
            required_level=AttenuationLevel.L2_STANDARD_OPERATOR,
            max_level=AttenuationLevel.L3_PRIVILEGED_AGENT
        ))

        # Attenuation escalation violation: requesting L4 when max is L2
        with self.assertRaises(AuthorizationDeniedError):
            self.rebac.authorize(
                subject="worker",
                relation="process",
                object_resource="queue",
                required_level=AttenuationLevel.L4_SOVEREIGN_ENCLAVE,
                max_level=AttenuationLevel.L2_STANDARD_OPERATOR
            )

    def test_subject_ceiling_blocks_self_escalation(self):
        """A subject may never hold a level above its own granted ceiling."""
        self.rebac.add_relation("auditor", "can_execute", "finance")
        self.assertEqual(
            self.rebac.ceiling_for("auditor"),
            AttenuationLevel.L2_STANDARD_OPERATOR,
        )

        with self.assertRaises(AuthorizationDeniedError):
            self.rebac.authorize(
                subject="auditor",
                relation="can_execute",
                object_resource="finance",
                required_level=AttenuationLevel.L4_SOVEREIGN_ENCLAVE,
            )

    def test_lease_never_exceeds_subject_ceiling(self):
        self.rebac.add_relation("auditor", "can_execute", "finance")
        with self.assertRaises(AuthorizationDeniedError):
            self.rebac.issue_lease(
                "auditor",
                "can_execute",
                "finance",
                level=AttenuationLevel.L3_PRIVILEGED_AGENT,
            )

    def test_unknown_subject_has_no_authority(self):
        self.assertEqual(
            self.rebac.ceiling_for("nobody"),
            AttenuationLevel.L0_UNAUTHENTICATED,
        )
        with self.assertRaises(AuthorizationDeniedError):
            self.rebac.authorize(
                subject="nobody",
                relation="can_execute",
                object_resource="finance",
            )

    def test_capability_lease_issuance_and_verification(self):
        self.rebac.add_relation("carol", "query", "crm")
        lease = self.rebac.issue_lease("carol", "query", "crm", level=AttenuationLevel.L2_STANDARD_OPERATOR)
        self.assertTrue(self.rebac.verify_lease(lease))

        # Tampered lease must fail verification
        lease.subject = "attacker"
        self.assertFalse(self.rebac.verify_lease(lease))

    def test_expired_lease_is_rejected(self):
        self.rebac.add_relation("carol", "query", "crm")
        lease = self.rebac.issue_lease(
            "carol", "query", "crm",
            level=AttenuationLevel.L2_STANDARD_OPERATOR,
            duration_seconds=0.0,
        )
        self.assertFalse(lease.is_valid)
        self.assertFalse(self.rebac.verify_lease(lease))

    def test_cyclic_group_membership_terminates(self):
        """A member_of cycle must terminate: group graphs are caller-supplied,
        and a cyclic one would otherwise exhaust the stack."""
        self.rebac.add_relation("team_a", "member_of", "team_b")
        self.rebac.add_relation("team_b", "member_of", "team_a")

        # Fails closed rather than recursing forever.
        self.assertFalse(self.rebac.check("team_a", "can_execute", "finance"))

        # And a real grant reachable through the cycle still resolves.
        self.rebac.add_relation("team_b", "can_execute", "finance")
        self.assertTrue(self.rebac.check("team_a", "can_execute", "finance"))

    def test_check_is_safe_against_concurrent_writers(self):
        """A decision must be made against a consistent snapshot: iterating the
        live store while another thread writes raises mid-evaluation."""
        for i in range(200):
            self.rebac.add_relation(f"seed_{i}", "member_of", "c_suite")

        errors = []

        def reader():
            for _ in range(2000):
                try:
                    self.rebac.check("seed_1", "can_execute", "finance")
                except Exception as exc:  # pragma: no cover - the bug under test
                    errors.append(repr(exc))
                    return

        def writer():
            for i in range(2000):
                self.rebac.add_relation(f"late_{i}", "member_of", "c_suite")

        threads = [threading.Thread(target=reader), threading.Thread(target=writer)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])

    def test_lease_secret_key_has_full_entropy(self):
        """HMAC lease keys must be 256-bit CSPRNG material, not a 128-bit UUID."""
        self.assertEqual(len(ZanzibarReBAC()._secret_key), 32)


if __name__ == "__main__":
    unittest.main()
