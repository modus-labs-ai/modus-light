"""
Modus Light — Main Client & Runtime Gateway
===========================================
Unified, lightweight developer interface connecting TokenShield,
FinOps Gateway, Zanzibar ReBAC, Linda Tuple Space, and the OTP Supervisor.
"""

import ast
import os
import threading
import time
from typing import Dict, Any, Tuple, Optional, List, Callable
from .types import (
    TaskTuple,
    CapabilityLease,
    AuditReport,
    ActorSpec,
    AttenuationLevel,
)
from .exceptions import AuthorizationDeniedError, ConfigurationError, SpendCapExceededError
from .token_shield import TokenShield
from .finops import FinOpsGateway, SpendReservation
from .rebac import ZanzibarReBAC
from .linda import TupleSpace
from .supervisor import OtpSupervisor

# Modules that would allow outbound network traffic. The runtime must not use them.
_NETWORK_MODULES = ("socket", "http", "urllib", "requests", "httpx", "aiohttp", "ftplib")


def _require(condition: Any, message: str) -> None:
    """
    Raises AssertionError when `condition` is falsy.

    The compliance audit states its verdicts through this function rather than
    through `assert`, because `python -O` strips assert statements at compile
    time. An audit written with bare asserts returns "16/16 PASSED" from an
    optimized container having verified nothing — a false attestation that is
    indistinguishable from a real one. `tests/test_no_asserts_in_src.py` enforces
    the rule for the whole package.
    """
    if not condition:
        raise AssertionError(message)


class ModusLight:
    """
    Modus Light Sovereign Runtime:
    Zero-token coordination, algorithmic FinOps kill switches,
    Zanzibar ReBAC capability leasing, and OTP-pattern crash resilience.
    """

    #: Applied when neither an argument nor an environment variable supplies a value.
    DEFAULT_TENANT_ID = "default_enterprise"
    DEFAULT_SPEND_CAP_TOKENS = 50000

    def __init__(
        self,
        tenant_id: Optional[str] = None,
        spend_cap_tokens: Optional[int] = None,
        enable_shield: bool = True,
        seed_default_policies: bool = True,
    ):
        """
        Explicit arguments win. Otherwise `MODUS_TENANT_ID` and
        `MODUS_SPEND_CAP_TOKENS` are read from the environment, so an operator can
        set the spend ceiling without touching code. A malformed
        `MODUS_SPEND_CAP_TOKENS` raises `ConfigurationError` rather than silently
        falling back to the default cap — a kill switch must never guess its limit.

        `seed_default_policies` controls the starter ReBAC policy, which grants
        the roles `system` and `admin` sovereign authority on every object so the
        demos and quickstart run out of the box. Pass False for an empty policy
        store and add only the relations your deployment intends. See
        `ZanzibarReBAC._seed_default_policies` — roles are caller-asserted
        strings, so authenticating the caller stays the application's job.
        """
        self.tenant_id = tenant_id or os.environ.get("MODUS_TENANT_ID") or self.DEFAULT_TENANT_ID

        if spend_cap_tokens is None:
            raw_cap = (os.environ.get("MODUS_SPEND_CAP_TOKENS") or "").strip()
            if not raw_cap:
                spend_cap_tokens = self.DEFAULT_SPEND_CAP_TOKENS
            else:
                try:
                    spend_cap_tokens = int(raw_cap)
                except ValueError as exc:
                    raise ConfigurationError(
                        "MODUS_SPEND_CAP_TOKENS must be an integer number of tokens, got "
                        f"{raw_cap!r}. Refusing to start with an unknown spend ceiling."
                    ) from exc

        self.token_shield = TokenShield() if enable_shield else None
        self.finops = FinOpsGateway(spend_cap_tokens=spend_cap_tokens)
        self.rebac = ZanzibarReBAC(seed_defaults=seed_default_policies)
        self.tuples = TupleSpace()
        self.supervisor = OtpSupervisor(strategy="one_for_one")
        # Outstanding reservations, oldest first. A list rather than one slot so a
        # second authorize_step() cannot orphan the first handle's hold on the cap.
        self._outstanding_reservations: List[SpendReservation] = []
        self._reservation_lock = threading.Lock()

    # ------------------------------------------------------------------
    # TokenShield
    # ------------------------------------------------------------------

    def shield_prompt(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Runs TokenShield zero-cost entity masking:
        Neutralizes Unicode/Bidi overrides, folds homoglyphs, and masks sensitive entities.
        Consumes 0 external LLM wire tokens.
        """
        if not self.token_shield:
            return text, {}
        return self.token_shield.shield(text)

    def unshield_text(self, text: str, token_map: Dict[str, str]) -> str:
        """Restores original entities using private in-memory token map."""
        if not self.token_shield:
            return text
        return self.token_shield.unshield(text, token_map)

    # ------------------------------------------------------------------
    # Combined authorization + spend gate
    # ------------------------------------------------------------------

    def authorize_step(
        self,
        role: str,
        sector: str,
        estimated_tokens: int = 100,
        required_level: AttenuationLevel = AttenuationLevel.L2_STANDARD_OPERATOR,
        prompt_tokens: int = 0,
    ) -> SpendReservation:
        """
        Combined gate for one execution step:
        1. Validates the Google Zanzibar ReBAC relationship policy.
        2. Reserves the estimated token cost against the Step 5 spend cap.

        Authorization is evaluated first, so a rejected caller can never burn
        another tenant's budget.

        `estimated_tokens` is the whole step, prompt plus generation. Declare
        `prompt_tokens` as well and `reservation.max_tokens` comes back as the
        generation budget that actually remains — the number to hand the provider
        as its output limit. Providers bill input and output, so a limit set to
        the whole reservation lets the step cost prompt + reservation and breach
        its ceiling on every call.

        Returns the reservation handle. Pass it to `commit_spend()` or
        `release_reservation()` to settle it — that is the concurrency-safe path.
        The handle is also tracked internally, so omitting it still works for
        simple single-step callers, and the object is truthy for code written
        against the older boolean return.
        """
        self.rebac.authorize(
            subject=role,
            relation="can_execute",
            object_resource=sector,
            required_level=required_level,
        )

        tier = self.finops.recommend_tier(estimated_tokens)
        reservation = self.finops.reserve(
            estimated_tokens, tier=tier, prompt_tokens=prompt_tokens
        )
        # Tracked in a list, not a single slot. Every component here is
        # lock-guarded for concurrent use, so two steps can legitimately be in
        # flight; with one slot the second call overwrites the first handle
        # before it settles, and with no other reference to it that hold on the
        # cap can never be released. Available budget then ratchets down until
        # every step is refused — an outage clearable only by a restart.
        with self._reservation_lock:
            self._outstanding_reservations.append(reservation)
        return reservation

    def _take_reservation(
        self, reservation: Optional[SpendReservation]
    ) -> Optional[SpendReservation]:
        """Removes and returns a tracked reservation (the oldest, if unspecified)."""
        with self._reservation_lock:
            if reservation is not None:
                if reservation in self._outstanding_reservations:
                    self._outstanding_reservations.remove(reservation)
                return reservation
            if self._outstanding_reservations:
                return self._outstanding_reservations.pop(0)
            return None

    def commit_spend(
        self,
        actual_tokens: int,
        tokens_saved: int = 0,
        reservation: Optional[SpendReservation] = None,
    ) -> int:
        """
        Settles a reservation with the real token cost of the step.
        Call this after the provider call returns.

        Pass the handle returned by `authorize_step()` when more than one step
        can be in flight; otherwise the oldest outstanding reservation is settled.
        """
        return self.finops.commit_spend(
            actual_tokens,
            reservation=self._take_reservation(reservation),
            tokens_saved=tokens_saved,
        )

    def release_reservation(self, reservation: Optional[SpendReservation] = None) -> None:
        """
        Releases a reservation when a step is abandoned before dispatch.

        Releases the handle given, or the oldest outstanding one. Safe to call
        from a `finally:` block: releasing an already-settled reservation is a
        no-op.
        """
        target = self._take_reservation(reservation)
        if target is not None:
            self.finops.release(target)

    def release_all_reservations(self) -> int:
        """
        Releases every outstanding reservation and returns how many were released.

        The recovery path for a coordinator that lost track of in-flight steps,
        so held budget can be reclaimed without restarting the process.
        """
        with self._reservation_lock:
            pending = self._outstanding_reservations
            self._outstanding_reservations = []
        for reservation in pending:
            self.finops.release(reservation)
        return len(pending)

    # ------------------------------------------------------------------
    # ReBAC
    # ------------------------------------------------------------------

    def issue_capability_lease(
        self,
        subject: str,
        relation: str,
        object_resource: str,
        level: AttenuationLevel = AttenuationLevel.L2_STANDARD_OPERATOR,
        duration_seconds: float = 300.0,
    ) -> CapabilityLease:
        """Issues an HMAC-SHA256 cryptographically signed capability lease."""
        return self.rebac.issue_lease(
            subject=subject,
            relation=relation,
            object_resource=object_resource,
            level=level,
            duration_seconds=duration_seconds,
        )

    def redeem_capability_lease(self, lease: CapabilityLease) -> bool:
        """
        Redeems a lease for a one-time action. Returns False if invalid or replayed.

        Use this for anything that must happen once — a transfer, a deployment, a
        privileged write. Verifying the signature alone proves the lease is
        authentic and unexpired, which defeats forgery but not replay: an attacker
        holding a captured lease can present it again for the rest of its TTL.
        Redemption spends the lease, so the second attempt is refused.

        Where a capability is legitimately reusable for its lifetime, such as read
        access within one session, verify it with `self.rebac.verify_lease` instead
        and leave it unredeemed.
        """
        return self.rebac.consume_lease(lease)

    # ------------------------------------------------------------------
    # Tuple space
    # ------------------------------------------------------------------

    def submit_task(
        self,
        topic: str,
        payload: Dict[str, Any],
        priority: int = 0,
        ttl_seconds: Optional[float] = None
    ) -> TaskTuple:
        """Emits a new task tuple into the Linda space without wire token bloat."""
        return self.tuples.out(
            topic=topic,
            payload=payload,
            tenant_id=self.tenant_id,
            priority=priority,
            ttl_seconds=ttl_seconds
        )

    def claim_task(self, worker_id: str, topic: Optional[str] = None) -> Optional[TaskTuple]:
        """Claims an exclusive execution lease on a pending task tuple."""
        return self.tuples.in_lease(worker_id=worker_id, topic=topic, tenant_id=self.tenant_id)

    def complete_task(
        self,
        tuple_id: int,
        result: Optional[Dict[str, Any]] = None,
        *,
        worker_id: str,
    ) -> bool:
        """
        Marks a task tuple completed.

        `worker_id` must be the worker that claimed the lease; the call returns
        False if the tuple is held by someone else, so one agent cannot close out
        another's work. It is required and keyword-only, because an optional
        owner check is not a lease. Returns False rather than raising, so a
        worker that lost a race can simply claim the next tuple.
        """
        return self.tuples.complete(
            tuple_id=tuple_id,
            result_payload=result,
            worker_id=worker_id,
        )

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def package_symlink_count(self) -> int:
        """Counts symlinks inside the installed package (deployment hygiene check)."""
        package_dir = os.path.dirname(os.path.abspath(__file__))
        count = 0
        for root, dirs, files in os.walk(package_dir):
            for name in list(dirs) + list(files):
                if os.path.islink(os.path.join(root, name)):
                    count += 1
        return count

    def network_transport_imports(self) -> List[str]:
        """
        Returns every network-transport import found in this package's own source.

        The check parses each module and walks its syntax tree. A text search
        cannot do this job in either direction: it reports a match for the words
        "import socket" sitting in a comment or a docstring, and it misses
        `__import__("socket")` and `importlib.import_module("socket")`, which are
        exactly the forms used when someone wants an import not to be obvious.

        Scoped to this package's files deliberately. Inspecting `sys.modules`
        instead would fail the audit because the *host application* imported
        `requests` — a true statement about the process, but not about this
        runtime, and not something a customer can act on.

        Each entry reads "module.py:lineno imports socket".
        """
        package_dir = os.path.dirname(os.path.abspath(__file__))
        findings: List[str] = []

        for root, _dirs, files in os.walk(package_dir):
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                try:
                    with open(path, "r", encoding="utf-8") as handle:
                        tree = ast.parse(handle.read(), filename=path)
                except (OSError, SyntaxError):
                    # Unreadable or unparseable source cannot be cleared, so it
                    # is reported rather than passed over.
                    findings.append(f"{name}: source could not be parsed for audit")
                    continue

                for node in ast.walk(tree):
                    # `import socket` / `import socket.foo`
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            root_mod = alias.name.split(".")[0]
                            if root_mod in _NETWORK_MODULES:
                                findings.append(f"{name}:{node.lineno} imports {root_mod}")
                    # `from socket import ...`; level > 0 is a relative import,
                    # which can only reach inside this package.
                    elif isinstance(node, ast.ImportFrom):
                        if node.level == 0 and node.module:
                            root_mod = node.module.split(".")[0]
                            if root_mod in _NETWORK_MODULES:
                                findings.append(f"{name}:{node.lineno} imports {root_mod}")
                    # `__import__("socket")` and `importlib.import_module("socket")`
                    elif isinstance(node, ast.Call):
                        target = node.func
                        called = ""
                        if isinstance(target, ast.Name):
                            called = target.id
                        elif isinstance(target, ast.Attribute):
                            called = target.attr
                        if called not in ("__import__", "import_module"):
                            continue
                        for arg in node.args:
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                root_mod = arg.value.split(".")[0]
                                if root_mod in _NETWORK_MODULES:
                                    findings.append(
                                        f"{name}:{node.lineno} dynamically imports {root_mod}"
                                    )

        return findings

    def network_free(self) -> bool:
        """
        True when no module in this package imports a network transport.

        This is what makes the air-gap claim checkable instead of decorative.
        Use `network_transport_imports()` to see *what* was found.
        """
        return not self.network_transport_imports()

    def check_health(self) -> Dict[str, Any]:
        """Returns the operational status of the Modus Light runtime."""
        supervisor_status = self.supervisor.get_status()
        degraded = supervisor_status["actors_tripped"] > 0 or supervisor_status["actors_failed"] > 0
        air_gap = self.network_free()
        return {
            "status": "DEGRADED" if degraded else "HEALTHY",
            "runtime_edition": "Modus Light (Community Edition)",
            "tenant_id": self.tenant_id,
            "finops": self.finops.get_finops_summary(),
            "actors": supervisor_status,
            "pending_tuples": self.tuples.count("PENDING"),
            "coordination_bus": "IN_PROCESS",
            "wire_tokens_consumed": 0,
            "air_gap_compliant": air_gap,
        }

    # ------------------------------------------------------------------
    # Smoke audit
    # ------------------------------------------------------------------

    def run_smoke_audit(self) -> AuditReport:
        """
        Runs the compliance smoke audit.

        Every check below is executed against the live runtime; nothing is
        hard-coded. A failing check is reported by name in `findings` and the
        report status becomes FAILED.
        """
        t0 = time.perf_counter()
        checks: List[Tuple[str, Callable[[], None]]] = [
            ("shield_masks_pii_entities", self._audit_shield_pii),
            ("shield_neutralizes_unicode_attacks", self._audit_shield_unicode),
            ("shield_roundtrip", self._audit_shield_roundtrip),
            ("shield_luhn_card_filtering", self._audit_shield_luhn),
            ("finops_over_cap_refusal", self._audit_finops_refusal),
            ("finops_reservation_accounting", self._audit_finops_accounting),
            ("rebac_unauthorized_denial", self._audit_rebac_denial),
            ("rebac_wildcard_grant", self._audit_rebac_wildcard),
            ("rebac_attenuation_ceiling", self._audit_rebac_ceiling),
            ("rebac_lease_signature_integrity", self._audit_rebac_lease),
            ("rebac_lease_replay_refused", self._audit_rebac_replay),
            ("rebac_lease_expiry_enforced", self._audit_rebac_expiry),
            ("linda_priority_then_fifo", self._audit_linda_order),
            ("supervisor_restart_recovery", self._audit_supervisor_restart),
            ("supervisor_circuit_breaker_trip", self._audit_supervisor_breaker),
            ("package_symlink_hygiene", self._audit_symlink_hygiene),
        ]

        findings: List[str] = []
        passed = 0
        for name, check in checks:
            try:
                check()
                passed += 1
            except Exception as exc:  # a failed check must never abort the audit
                findings.append(f"{name}: {exc}")

        elapsed = time.perf_counter() - t0
        return AuditReport(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            checks_total=len(checks),
            checks_passed=passed,
            checks_failed=len(checks) - passed,
            duration_seconds=round(elapsed, 4),
            wire_tokens_consumed=0,
            symlink_count=self.package_symlink_count(),
            findings=findings,
            status="PASSED" if not findings else "FAILED",
        )

    # -- individual audit checks ----------------------------------------

    def _audit_shield_pii(self):
        masked, token_map = self.shield_prompt(
            "Contact ops@example.com at 192.0.2.10 with key sk-ant-live-0123456789abcdef"
        )
        _require("ops@example.com" not in masked, "email was not masked")
        _require("192.0.2.10" not in masked, "IP address was not masked")
        _require("sk-ant-live-0123456789abcdef" not in masked, "secret was not masked")
        _require(len(token_map) == 3, f"expected 3 masked entities, got {len(token_map)}")

    def _audit_shield_unicode(self):
        masked, _ = self.shield_prompt("Cyrillic а and zero\u200Bwidth and bidi \u202Eoverride")
        _require("\u200B" not in masked, "zero-width character survived")
        _require("\u202E" not in masked, "bidi override survived")
        _require("Cyrillic a" in masked, "homoglyph was not folded")

    def _audit_shield_roundtrip(self):
        original = "Send wire to user@example.com on 192.0.2.25"
        masked, token_map = self.shield_prompt(original)
        _require(self.unshield_text(masked, token_map) == original, "unshield did not restore the original text")

    def _audit_shield_luhn(self):
        masked, _ = self.shield_prompt("card 4111111111111111 and id 1234567890123456")
        _require("4111111111111111" not in masked, "Luhn-valid card was not masked")
        _require("1234567890123456" in masked, "non-card number was masked by mistake")

    def _audit_finops_refusal(self):
        gateway = FinOpsGateway(spend_cap_tokens=100)
        try:
            gateway.reserve(500)
        except SpendCapExceededError:
            return
        raise AssertionError("over-cap reservation was not refused")

    def _audit_finops_accounting(self):
        gateway = FinOpsGateway(spend_cap_tokens=1000)
        reservation = gateway.reserve(300)
        _require(gateway.remaining_budget == 700, f"unexpected remaining budget {gateway.remaining_budget}")
        gateway.commit_spend(250, reservation=reservation)
        summary = gateway.get_finops_summary()
        _require(summary["consumed_tokens"] == 250, f"unexpected consumed tokens {summary['consumed_tokens']}")
        _require(summary["reserved_tokens"] == 0, f"reservation not settled: {summary['reserved_tokens']}")
        _require(summary["remaining_tokens"] == 750, f"unexpected remaining {summary['remaining_tokens']}")

    def _audit_rebac_denial(self):
        try:
            self.rebac.authorize(
                subject="guest_attacker_admin",
                relation="can_execute",
                object_resource="cyber_defense",
            )
        except AuthorizationDeniedError:
            return
        raise AssertionError("unauthorized subject was admitted")

    def _audit_rebac_wildcard(self):
        _require(self.rebac.check("admin", "can_execute", "cyber_defense"), "admin wildcard grant missing")

    def _audit_rebac_ceiling(self):
        # A throwaway engine, not self.rebac. This audit is exposed as the
        # `modus-light audit` subcommand and reads like a health check, but
        # writing the grant into the live policy store permanently gave the
        # `auditor` principal execute authority over the `finance` sector and
        # raised its ceiling. A compliance check must not mutate the policy it
        # is checking.
        rebac = ZanzibarReBAC()
        rebac.add_relation("auditor", "can_execute", "finance")
        try:
            rebac.authorize(
                subject="auditor",
                relation="can_execute",
                object_resource="finance",
                required_level=AttenuationLevel.L4_SOVEREIGN_ENCLAVE,
            )
        except AuthorizationDeniedError:
            return
        raise AssertionError("subject obtained a level above its authority ceiling")

    def _audit_rebac_lease(self):
        rebac = ZanzibarReBAC()  # throwaway: never mutate the live policy store
        rebac.add_relation("auditor", "can_execute", "finance")
        lease = rebac.issue_lease(
            "auditor", "can_execute", "finance", level=AttenuationLevel.L2_STANDARD_OPERATOR
        )
        _require(rebac.verify_lease(lease), "valid lease failed verification")
        lease.subject = "attacker"
        _require(not rebac.verify_lease(lease), "tampered lease passed verification")

    def _audit_rebac_replay(self):
        rebac = ZanzibarReBAC()  # throwaway: never mutate the live policy store
        rebac.add_relation("auditor", "can_execute", "finance")
        lease = rebac.issue_lease(
            "auditor", "can_execute", "finance", level=AttenuationLevel.L2_STANDARD_OPERATOR
        )
        _require(rebac.consume_lease(lease), "valid lease could not be redeemed")
        _require(
            not rebac.consume_lease(lease),
            "replayed lease was redeemed a second time",
        )

    def _audit_rebac_expiry(self):
        rebac = ZanzibarReBAC()  # throwaway: never mutate the live policy store
        rebac.add_relation("auditor", "can_execute", "finance")
        lease = rebac.issue_lease(
            "auditor", "can_execute", "finance",
            level=AttenuationLevel.L2_STANDARD_OPERATOR,
            duration_seconds=0.0,
        )
        _require(not lease.is_valid, "expired lease reported as valid")
        _require(not rebac.verify_lease(lease), "expired lease passed verification")

    def _audit_linda_order(self):
        space = TupleSpace()
        # Two tuples share priority 1 so that FIFO *within* a priority is actually
        # exercised. The check is named for both properties; before this it only
        # ever compared two different priorities, so the tie-break the name claims
        # was asserted in prose only.
        first_low = space.out("q", {"n": "low-1"}, priority=1)
        second_low = space.out("q", {"n": "low-2"}, priority=1)
        crit = space.out("q", {"n": "critical"}, priority=100)

        claimed = []
        for worker in ("w1", "w2", "w3"):
            t = space.in_lease(worker_id=worker, topic="q")
            _require(t is not None, f"{worker} could not claim a tuple from a space of 3")
            claimed.append(t.id)  # type: ignore[union-attr]  # reason: _require above proves not None

        _require(claimed[0] == crit.id, f"priority order violated: served {claimed[0]} before {crit.id}")
        _require(
            claimed[1:] == [first_low.id, second_low.id],
            f"FIFO within a priority violated: got {claimed[1:]}, expected {[first_low.id, second_low.id]}",
        )

    def _audit_supervisor_restart(self):
        supervisor = OtpSupervisor(strategy="one_for_one", max_restarts=3, window_seconds=5.0)
        state = {"attempts": 0}

        def flaky():
            state["attempts"] += 1
            if state["attempts"] < 2:
                raise RuntimeError("transient socket failure")
            return "recovered"

        supervisor.register_actor(ActorSpec(name="flaky", role="worker"), flaky)
        _require(supervisor.execute_actor("flaky") == "recovered", "actor did not recover via restart")

    def _audit_supervisor_breaker(self):
        supervisor = OtpSupervisor(strategy="one_for_one", max_restarts=2, window_seconds=5.0)

        def always_fails():
            raise RuntimeError("permanent failure")

        supervisor.register_actor(ActorSpec(name="broken", role="worker"), always_fails)
        try:
            supervisor.execute_actor("broken")
        except Exception as exc:
            _require(type(exc).__name__ == "CircuitBreakerTrippedError", f"unexpected error {exc!r}")
        else:
            raise AssertionError("circuit breaker did not trip")
        _require(supervisor.get_status()["actors_tripped"] == 1, "actor was not marked as tripped")

    def _audit_symlink_hygiene(self):
        count = self.package_symlink_count()
        _require(count == 0, f"{count} symlink(s) found inside the installed package")
