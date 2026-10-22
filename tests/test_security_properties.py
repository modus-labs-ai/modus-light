"""
Security property tests
=======================
Each test here pins one property that the runtime's safety claims depend on —
the kind of property that a refactor can quietly drop while every other test
stays green, because nothing else exercises the failure direction.

Every docstring states *why* the property matters and what goes wrong without
it. A test whose reason for existing is unrecorded is the first thing somebody
deletes to make a refactor pass.
"""

import ast
import pathlib
import random
import subprocess
import sys
import time
import unittest

from modus_light import ModusLight
from modus_light.finops import FinOpsGateway
from modus_light.linda import TupleSpace
from modus_light.rebac import ZanzibarReBAC
from modus_light.token_shield import TokenShield
from modus_light.types import AttenuationLevel, ModelTier
from modus_light.exceptions import AuthorizationDeniedError, SpendCapExceededError

SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "src" / "modus_light"


class TestNoAssertStatementsInShippedCode(unittest.TestCase):
    """`python -O` strips assert statements, so they cannot carry a guarantee."""

    def test_no_module_in_the_package_uses_assert(self):
        """No shipped module may state a check through `assert`.

        `python -O` removes assert statements at compile time. A compliance
        audit built on them reports "16/16 PASSED" from an optimized container
        having verified nothing — a false attestation indistinguishable from a
        real one. Checks state their verdicts through `_require()`, a real
        function call that survives optimization.
        """
        offenders = []
        for path in sorted(SRC_DIR.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assert):
                    offenders.append(f"{path.name}:{node.lineno}")

        self.assertEqual(
            offenders, [],
            "assert statements found in shipped code; `python -O` deletes these "
            f"entirely. Use `_require()` or an explicit raise instead: {offenders}",
        )

    def test_the_audit_still_passes_under_optimized_python(self):
        """The audit must reach the same verdict with -O as without it."""
        result = subprocess.run(
            [sys.executable, "-O", "-c",
             "from modus_light import ModusLight;"
             "r = ModusLight().run_smoke_audit();"
             "print(r.checks_passed, r.checks_total, r.status)"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "16 16 PASSED")


class TestFinOpsKillSwitchCannotBeDisabledByItsOwnArgument(unittest.TestCase):

    def setUp(self):
        self.gateway = FinOpsGateway(spend_cap_tokens=1000)

    def test_a_negative_estimate_cannot_credit_the_budget(self):
        """A negative estimate would pass the ceiling test and *add* headroom,
        so `reserve(-10**9)` would hand the caller an unlimited budget."""
        for bad in (-1, -10 ** 9, -0.5):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    self.gateway.reserve(bad)
        self.assertEqual(self.gateway.current_spend, 0)

    def test_a_nan_estimate_cannot_permanently_open_the_gate(self):
        """Every comparison against NaN is False, so a NaN estimate would make
        the ceiling test unable to trip at all."""
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    self.gateway.pre_dispatch_check(bad)

    def test_a_non_numeric_estimate_is_refused(self):
        for bad in ("100", None, True, [100]):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    self.gateway.reserve(bad)

    def test_a_reservation_settles_exactly_once(self):
        """A reservation is a one-shot claim: committing one handle twice would
        decrement the reserve twice and silently free another step's hold."""
        reservation = self.gateway.reserve(200)
        self.gateway.commit_spend(200, reservation=reservation)
        with self.assertRaises(ValueError):
            self.gateway.commit_spend(200, reservation=reservation)

    def test_releasing_a_settled_reservation_is_a_no_op(self):
        """So a `finally:` block can release without knowing whether it committed."""
        reservation = self.gateway.reserve(200)
        self.gateway.commit_spend(200, reservation=reservation)
        self.gateway.release(reservation)
        self.assertEqual(self.gateway.get_finops_summary()["reserved_tokens"], 0)

    def test_a_later_expensive_tier_does_not_reprice_earlier_spend(self):
        """Cost accrues at the tier each step ran on. Deriving it from the token
        total and the latest tier would let one PRO step restate every earlier
        FLASH_LITE token at 50x its real price."""
        cheap = self.gateway.reserve(1000, tier=ModelTier.FLASH_LITE)
        self.gateway.commit_spend(1000, reservation=cheap)
        after_cheap = self.gateway.get_finops_summary()["estimated_spend_usd"]
        self.assertAlmostEqual(after_cheap, 0.0001, places=6)

        pricey = FinOpsGateway(spend_cap_tokens=10000)
        first = pricey.reserve(1000, tier=ModelTier.FLASH_LITE)
        pricey.commit_spend(1000, reservation=first)
        second = pricey.reserve(1000, tier=ModelTier.PRO)
        pricey.commit_spend(1000, reservation=second)
        # 0.0001 (FLASH_LITE) + 0.0050 (PRO), not 2 x 0.0050.
        self.assertAlmostEqual(
            pricey.get_finops_summary()["estimated_spend_usd"], 0.0051, places=6
        )


class TestReservationHandlesAreTrackedPerHandle(unittest.TestCase):

    def setUp(self):
        self.rt = ModusLight(tenant_id="t", spend_cap_tokens=1000)

    def test_two_steps_in_flight_both_settle(self):
        """Reservations are tracked per handle, not in one slot.

        With a single slot, a second authorize_step() overwrites the first
        handle before it settles; no other reference to it exists, so its hold
        on the cap can never be released and available budget ratchets down
        until every step is refused — an outage clearable only by a restart."""
        first = self.rt.authorize_step("admin", "security", 300)
        second = self.rt.authorize_step("admin", "security", 300)
        self.assertEqual(self.rt.finops.get_finops_summary()["reserved_tokens"], 600)

        self.rt.commit_spend(300, reservation=second)
        self.rt.release_reservation(first)

        summary = self.rt.finops.get_finops_summary()
        self.assertEqual(summary["reserved_tokens"], 0)
        self.assertEqual(summary["consumed_tokens"], 300)
        self.assertEqual(summary["remaining_tokens"], 700)

    def test_release_all_reclaims_every_outstanding_hold(self):
        """The recovery path for a coordinator that lost track of in-flight
        steps, so held budget can be reclaimed without restarting."""
        self.rt.authorize_step("admin", "security", 200)
        self.rt.authorize_step("admin", "security", 200)
        self.assertEqual(self.rt.release_all_reservations(), 2)
        self.assertEqual(self.rt.finops.get_finops_summary()["reserved_tokens"], 0)

    def test_the_handle_is_truthy_for_callers_written_against_the_bool_return(self):
        self.assertTrue(self.rt.authorize_step("admin", "security", 100))


class TestLeaseOwnershipIsEnforcedNotAdvisory(unittest.TestCase):

    def test_completing_without_a_worker_id_is_a_type_error(self):
        """Lease ownership must not be skippable by omitting an argument.

        An optional `worker_id` makes the check vanish for any caller that
        leaves it out, and tuple ids are sequential and so guessable — any agent
        in the process could then close out and overwrite work it never
        claimed."""
        space = TupleSpace()
        tuple_ = space.out("jobs", {"n": 1})
        space.in_lease(worker_id="agent_a", topic="jobs")
        with self.assertRaises(TypeError):
            space.complete(tuple_.id)  # type: ignore[call-arg]  # reason: proving it is required

    def test_a_foreign_worker_cannot_close_out_held_work(self):
        space = TupleSpace()
        space.out("jobs", {"n": 1})
        claimed = space.in_lease(worker_id="agent_a", topic="jobs")
        self.assertIsNotNone(claimed)
        assert claimed is not None  # narrows the type; no side effect
        self.assertFalse(space.complete(claimed.id, worker_id="agent_b"))
        self.assertEqual(claimed.status, "LEASED")
        self.assertTrue(space.complete(claimed.id, worker_id="agent_a"))


class TestTupleTimeToLive(unittest.TestCase):

    def test_a_zero_ttl_expires_rather_than_living_forever(self):
        """`ttl_seconds=0` means expire now; only None means never expire.

        A truthiness test on the TTL collapses the two and grants the immortal
        case to the caller who asked for the shortest possible life."""
        space = TupleSpace()
        tuple_ = space.out("jobs", {"n": 1}, ttl_seconds=0)
        self.assertIsNotNone(tuple_.expires_at)
        self.assertIsNone(space.in_lease(worker_id="w", topic="jobs"))


class TestAttenuationIsPerGrantNotPerSubject(unittest.TestCase):

    def setUp(self):
        self.rebac = ZanzibarReBAC()

    def test_a_high_grant_on_one_resource_confers_nothing_on_another(self):
        """Authority is per resource. A per-subject ceiling would let an L4 grant
        on a harmless sandbox raise the same subject's authority over payments."""
        self.rebac.add_relation(
            "contractor", "can_execute", "sandbox",
            max_level=AttenuationLevel.L4_SOVEREIGN_ENCLAVE,
        )
        self.rebac.add_relation(
            "contractor", "can_execute", "payments",
            max_level=AttenuationLevel.L1_READ_ONLY,
        )

        self.assertEqual(
            self.rebac.effective_level("contractor", "can_execute", "sandbox"),
            AttenuationLevel.L4_SOVEREIGN_ENCLAVE,
        )
        with self.assertRaises(AuthorizationDeniedError):
            self.rebac.authorize(
                "contractor", "can_execute", "payments",
                required_level=AttenuationLevel.L2_STANDARD_OPERATOR,
            )

    def test_revoking_a_grant_lowers_authority(self):
        """Revocation must actually remove authority, not leave a stale ceiling
        behind — otherwise an offboarded subject keeps the level it was given."""
        self.rebac.add_relation(
            "temp", "can_execute", "vault",
            max_level=AttenuationLevel.L3_PRIVILEGED_AGENT,
        )
        self.assertEqual(
            self.rebac.effective_level("temp", "can_execute", "vault"),
            AttenuationLevel.L3_PRIVILEGED_AGENT,
        )
        self.rebac.remove_relation("temp", "can_execute", "vault")
        self.assertIsNone(self.rebac.effective_level("temp", "can_execute", "vault"))

    def test_authority_attenuates_along_a_delegation_path(self):
        """Level_child <= Level_parent, enforced rather than documented: a weak
        membership edge into a powerful group must not confer the group's power."""
        self.rebac.add_relation(
            "privileged_group", "can_execute", "reactor",
            max_level=AttenuationLevel.L4_SOVEREIGN_ENCLAVE,
        )
        self.rebac.add_relation(
            "intern", "member_of", "privileged_group",
            max_level=AttenuationLevel.L1_READ_ONLY,
        )
        self.assertEqual(
            self.rebac.effective_level("intern", "can_execute", "reactor"),
            AttenuationLevel.L1_READ_ONLY,
        )


class TestLeaseSignaturesAreUnambiguous(unittest.TestCase):

    def test_a_colon_in_a_field_cannot_reinterpret_the_grant(self):
        """Lease signing must be injective over its fields.

        Joining them with ':' is ambiguous when a field contains a colon: a lease
        for object `public:admin_panel` and one for relation `can_execute:public`
        on `admin_panel` would share signing input, so a single signature would
        verify two different grants. Length-prefixing makes that impossible."""
        rebac = ZanzibarReBAC()
        rebac.add_relation("svc", "can_execute", "public:admin_panel")
        genuine = rebac.issue_lease("svc", "can_execute", "public:admin_panel")
        self.assertTrue(rebac.verify_lease(genuine))

        reinterpreted = type(genuine)(
            lease_id=genuine.lease_id,
            subject=genuine.subject,
            relation="can_execute:public",
            object_resource="admin_panel",
            attenuation_level=genuine.attenuation_level,
            granted_at=genuine.granted_at,
            expires_at=genuine.expires_at,
            signature=genuine.signature,
        )
        self.assertFalse(rebac.verify_lease(reinterpreted))


class TestLeasesAreSingleUseWhenRedeemed(unittest.TestCase):
    """Signature checking stops forgery; it does not stop replay."""

    def setUp(self):
        self.rebac = ZanzibarReBAC()

    def test_a_redeemed_lease_cannot_be_replayed(self):
        """A captured lease is otherwise usable as often as an attacker likes,
        for the whole of its TTL. Redemption is what makes it single-use."""
        lease = self.rebac.issue_lease("admin", "can_execute", "finance")
        self.assertTrue(self.rebac.consume_lease(lease))
        self.assertFalse(self.rebac.consume_lease(lease))

    def test_verify_stays_non_consuming_for_reusable_capabilities(self):
        """Not every capability should be single-use, so the two are separate
        operations: verify_lease answers "is this authentic", consume_lease
        answers "may this be redeemed now"."""
        lease = self.rebac.issue_lease("admin", "can_execute", "finance")
        self.assertTrue(self.rebac.verify_lease(lease))
        self.assertTrue(self.rebac.verify_lease(lease))
        self.assertEqual(self.rebac.consumed_lease_count, 0)

    def test_a_tampered_lease_is_never_redeemed(self):
        lease = self.rebac.issue_lease("admin", "can_execute", "finance")
        forged = type(lease)(
            lease_id=lease.lease_id,
            subject=lease.subject,
            relation=lease.relation,
            object_resource="payroll",
            attenuation_level=lease.attenuation_level,
            granted_at=lease.granted_at,
            expires_at=lease.expires_at,
            signature=lease.signature,
        )
        self.assertFalse(self.rebac.consume_lease(forged))

    def test_the_replay_registry_does_not_grow_without_bound(self):
        """Expired ids are forgotten: an expired lease is refused on its own, so
        remembering it protects nothing and would accumulate forever."""
        lease = self.rebac.issue_lease(
            "admin", "can_execute", "finance", duration_seconds=0.05
        )
        self.assertTrue(self.rebac.consume_lease(lease))
        self.assertEqual(self.rebac.consumed_lease_count, 1)
        time.sleep(0.1)
        self.assertEqual(self.rebac.consumed_lease_count, 0)
        # And it is still refused, now on expiry rather than on replay.
        self.assertFalse(self.rebac.consume_lease(lease))


class TestSpendCeilingBindsTheProviderCall(unittest.TestCase):

    def test_a_step_cannot_settle_above_the_budget_it_was_granted(self):
        """The guarantee is "a step spends no more than it was allotted". That
        holds only if settling above the ceiling is refused; otherwise the cap
        governs a number the caller volunteered and nothing more."""
        gateway = FinOpsGateway(spend_cap_tokens=1000)
        reservation = gateway.reserve(100)
        with self.assertRaises(SpendCapExceededError):
            gateway.commit_spend(900, reservation=reservation)
        self.assertEqual(gateway.get_finops_summary()["ceiling_breaches"], 1)

    def test_total_spend_cannot_exceed_the_cap_when_every_step_is_reserved(self):
        """This is the whole basis of the $0.00 overdraft guarantee.

        `reserve()` refuses anything above the *remaining* budget, where remaining
        already nets out tokens spent and tokens held. So the reserved total can
        never exceed the cap, and with the ceiling enforced no step settles above
        its reservation — therefore spend <= reservations <= cap. Randomised step
        sizes here rather than one hand-picked sequence, because the property is
        meant to hold for every schedule, not a convenient one.
        """
        random.seed(20261022)
        for _ in range(200):
            cap = random.randint(500, 5000)
            gateway = FinOpsGateway(spend_cap_tokens=cap)
            refusals = 0
            for _ in range(40):
                want = random.randint(1, cap // 2)
                try:
                    reservation = gateway.reserve(want)
                except SpendCapExceededError:
                    refusals += 1
                    continue
                # Settle anywhere within the ceiling, including exactly at it.
                gateway.commit_spend(random.randint(0, reservation.amount),
                                     reservation=reservation)
            summary = gateway.get_finops_summary()
            self.assertLessEqual(summary["consumed_tokens"], cap)
            self.assertEqual(summary["overdraft_tokens"], 0)
            self.assertEqual(summary["overdraft_amount"], 0.0)
            self.assertEqual(summary["ceiling_breaches"], 0)
            # If nothing was ever refused the cap was never approached, and the
            # assertions above would hold trivially.
            self.assertGreater(refusals, 0)

    def test_the_provider_ceiling_excludes_the_prompt(self):
        """Providers bill input and output. A ceiling that ignores the prompt is
        not a ceiling: handing the provider the full reservation as its output
        limit lets the step cost prompt + reservation and breach every time."""
        gateway = FinOpsGateway(spend_cap_tokens=10000)
        reservation = gateway.reserve(1000, prompt_tokens=700)
        self.assertEqual(reservation.max_tokens, 300)
        # Worst case the provider can produce: the prompt plus its whole limit.
        self.assertLessEqual(
            reservation.prompt_tokens + reservation.max_tokens, reservation.amount
        )

    def test_a_reservation_with_no_room_to_generate_is_refused(self):
        gateway = FinOpsGateway(spend_cap_tokens=10000)
        with self.assertRaises(ValueError):
            gateway.reserve(500, prompt_tokens=500)

    def test_a_breached_reservation_is_not_left_outstanding(self):
        """The raise must not strand the handle: a handle still sitting in the
        client's outstanding list holds budget that nothing will ever release."""
        runtime = ModusLight(spend_cap_tokens=5000)
        runtime.rebac.add_relation("admin", "can_execute", "finance")
        reservation = runtime.authorize_step("admin", "finance", estimated_tokens=100)
        with self.assertRaises(SpendCapExceededError):
            runtime.commit_spend(900, reservation=reservation)
        self.assertEqual(runtime.release_all_reservations(), 0)
        self.assertEqual(runtime.finops.get_finops_summary()["reserved_tokens"], 0)

    def test_the_breach_is_recorded_rather_than_swallowed(self):
        """The tokens are already spent by the time this is detected, so the
        telemetry must show it; the only question is whether the operator learns
        it now or from an invoice."""
        gateway = FinOpsGateway(spend_cap_tokens=1000)
        reservation = gateway.reserve(100)
        with self.assertRaises(SpendCapExceededError):
            gateway.commit_spend(900, reservation=reservation)
        summary = gateway.get_finops_summary()
        self.assertEqual(summary["consumed_tokens"], 900)
        self.assertGreater(summary["estimated_spend_usd"], 0.0)


class TestSecretPrefixCoverage(unittest.TestCase):

    def setUp(self):
        self.shield = TokenShield()

    def test_the_live_token_families_are_masked(self):
        """Every live credential prefix must be masked, not just the common two.

        Stripe issues underscore forms and GitHub has five prefixes; a pattern
        matching only `sk-` and `ghp_` forwards the rest to the provider
        verbatim, which is the exact leak TokenShield exists to prevent."""
        secrets_ = [
            "sk_live_" + "a" * 24,
            "sk_test_" + "b" * 24,
            "rk_live_" + "c" * 24,
            "gho_" + "d" * 36,
            "ghs_" + "e" * 36,
            "ghu_" + "f" * 36,
            "ghr_" + "g" * 36,
            "ghp_" + "h" * 36,
        ]
        for secret in secrets_:
            with self.subTest(secret=secret[:8]):
                masked, token_map = self.shield.shield(f"key is {secret} ok")
                self.assertNotIn(secret, masked)
                self.assertEqual(list(token_map.values()), [secret])

    def test_ordinary_prose_is_not_mangled(self):
        """The widened pattern must not start masking English."""
        prose = "risk_assessment_document and skeleton_key_policy_review, ticket 1234567812345670x"
        masked, token_map = self.shield.shield(prose)
        self.assertEqual(masked, prose)
        self.assertEqual(token_map, {})


class TestAuditExitCode(unittest.TestCase):

    def test_a_failing_audit_exits_non_zero(self):
        """A failing audit must be visible to a pipeline, not just to a reader.

        An audit that prints findings and exits 0 keeps CI green while reporting
        failure, which makes the gate decorative."""
        script = (
            "import sys;"
            "from modus_light import client as c;"
            "orig = c.ModusLight._audit_finops_refusal;"
            "c.ModusLight._audit_finops_refusal = "
            "lambda self: (_ for _ in ()).throw(AssertionError('simulated'));"
            "from modus_light.cli import main;"
            "sys.exit(main(['audit']))"
        )
        result = subprocess.run(
            [sys.executable, "-O", "-c", script],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 1, f"stdout={result.stdout}")
        self.assertIn("FAILED", result.stdout)


if __name__ == "__main__":
    unittest.main()
