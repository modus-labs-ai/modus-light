"""
Modus Light — Google Zanzibar ReBAC Engine
==========================================
Fine-grained Relationship-Based Access Control (ReBAC) with
strict 5-level monotonic capability attenuation and HMAC capability leasing.

Scope note: Zanzibar usersets (`group:eng#member`) are modelled here as
`member_of` tuples, which covers the transitive group case without the full
Zanzibar consistency-model machinery.
"""

import hmac
import hashlib
import secrets
import threading
import time
import uuid
from typing import Set, Tuple, Dict, Optional
from .types import AttenuationLevel, CapabilityLease
from .exceptions import AuthorizationDeniedError


class ZanzibarReBAC:
    """
    Google Zanzibar ReBAC Engine:
    Stores subject-relation-object tuples, evaluates access policies,
    and issues cryptographically signed capability leases with monotonic attenuation.
    """

    # Monotonic attenuation hierarchy: higher levels cannot be granted by lower authorities
    ATTENUATION_RANK = {
        AttenuationLevel.L0_UNAUTHENTICATED: 0,
        AttenuationLevel.L1_READ_ONLY: 1,
        AttenuationLevel.L2_STANDARD_OPERATOR: 2,
        AttenuationLevel.L3_PRIVILEGED_AGENT: 3,
        AttenuationLevel.L4_SOVEREIGN_ENCLAVE: 4,
    }

    def __init__(
        self,
        secret_key: Optional[bytes] = None,
        seed_defaults: bool = True,
    ):
        # Ephemeral 256-bit secret key for capability lease HMAC generation
        self._secret_key = secret_key or secrets.token_bytes(32)
        # Guards the tuple store so concurrent writers cannot corrupt a read
        self._lock = threading.RLock()
        # Set of active (subject, relation, object) tuples
        self._tuples: Set[Tuple[str, str, str]] = set()
        # Attenuation ceiling carried by each individual grant, keyed on the tuple
        # it was granted on. Per-grant rather than a per-subject scalar, because a
        # scalar conflates two different authorities: an L4 grant on a harmless
        # sandbox would raise the subject's level on every other resource it
        # related to, and revoking that grant could not lower it again. Keying on
        # the grant makes revocation lower authority by construction.
        self._grants: Dict[Tuple[str, str, str], AttenuationLevel] = {}
        # Lease ids already redeemed through consume_lease(), with the expiry that
        # lets them be forgotten. This is what makes single-use leases replay-proof
        # rather than merely forgery-proof: a signature check alone accepts a
        # captured lease as many times as an attacker cares to present it.
        self._consumed_leases: Dict[str, float] = {}
        if seed_defaults:
            self._seed_default_policies()

    def _seed_default_policies(self):
        """
        Seeds the baseline relations the demos and CLI rely on.

        Read this before deploying. These seeds grant `system` and, through
        `c_suite`, `admin` sovereign authority on every object (`*`). The subject
        of every decision is a plain string supplied by the caller, so this
        engine answers "what may the role named `admin` do", never "is this
        request really from an administrator". Authenticating the caller and
        mapping it to a role is the surrounding application's job; pass an
        unvalidated, user-controlled role string and the word "admin" is all the
        authority anyone needs.

        Construct with `ZanzibarReBAC(seed_defaults=False)` for an empty policy
        store, then add only the relations your deployment actually intends.
        """
        # System admin has sovereign authority across all sectors
        self.add_relation(
            "admin", "member_of", "c_suite",
            max_level=AttenuationLevel.L4_SOVEREIGN_ENCLAVE,
        )
        self.add_relation(
            "c_suite", "can_execute", "*",
            max_level=AttenuationLevel.L4_SOVEREIGN_ENCLAVE,
        )
        self.add_relation(
            "system", "can_execute", "*",
            max_level=AttenuationLevel.L4_SOVEREIGN_ENCLAVE,
        )

    def add_relation(
        self,
        subject: str,
        relation: str,
        object_resource: str,
        max_level: AttenuationLevel = AttenuationLevel.L2_STANDARD_OPERATOR,
    ):
        """
        Adds a subject-relation-object tuple to the policy store.

        `max_level` is the highest attenuation level this *grant* confers. It is
        scoped to the tuple, not to the subject: an L4 grant on one resource
        confers nothing on another, and removing the grant removes the authority.
        Re-granting the same tuple at a higher level raises that grant's ceiling.
        """
        clean_subj = subject.strip().lower()
        clean_rel = relation.strip().lower()
        clean_obj = object_resource.strip().lower()
        key = (clean_subj, clean_rel, clean_obj)
        with self._lock:
            self._tuples.add(key)
            current = self._grants.get(key, AttenuationLevel.L0_UNAUTHENTICATED)
            if self.ATTENUATION_RANK[max_level] > self.ATTENUATION_RANK[current]:
                self._grants[key] = max_level

    def remove_relation(self, subject: str, relation: str, object_resource: str):
        """
        Removes a relationship tuple from the policy store.

        The authority the grant conferred goes with it: because ceilings are
        keyed on the grant, revocation lowers the subject's effective level for
        that object instead of leaving a stale ceiling behind forever.
        """
        clean_subj = subject.strip().lower()
        clean_rel = relation.strip().lower()
        clean_obj = object_resource.strip().lower()
        key = (clean_subj, clean_rel, clean_obj)
        with self._lock:
            self._tuples.discard(key)
            self._grants.pop(key, None)

    def ceiling_for(self, subject: str) -> AttenuationLevel:
        """
        Returns the highest level this subject could reach through any one of its
        own direct grants.

        This is a summary, not an authorization decision: authority is per-object,
        so use `effective_level()` (or `authorize()`) to ask what a subject may do
        to a specific resource.
        """
        clean_subj = subject.strip().lower()
        with self._lock:
            levels = [
                level for (s, _r, _o), level in self._grants.items() if s == clean_subj
            ]
        if not levels:
            return AttenuationLevel.L0_UNAUTHENTICATED
        return max(levels, key=lambda lv: self.ATTENUATION_RANK[lv])

    def effective_level(
        self, subject: str, relation: str, object_resource: str
    ) -> Optional[AttenuationLevel]:
        """
        Returns the highest level `subject` can legitimately hold for this exact
        relation and object, or None when no grant authorizes it at all.

        Authority attenuates along a delegation path: reaching a resource through
        `member_of` caps the result at the level of the weakest edge traversed, so
        a member's authority can never exceed the authority of the group that lent
        it — the `Level_child <= Level_parent` property, enforced here rather than
        asserted in the documentation.
        """
        clean_rel = relation.strip().lower()
        clean_obj = object_resource.strip().lower()

        # Snapshot the store under the lock: a concurrent add_relation must never
        # mutate the mapping we are walking ("dictionary changed size during
        # iteration"), and a decision must be made against one consistent policy.
        with self._lock:
            grants = dict(self._grants)

        def rank(level: AttenuationLevel) -> int:
            return self.ATTENUATION_RANK[level]

        # Breadth-first walk over `member_of` edges, carrying the remaining
        # attenuation budget. `best_budget` makes a cyclic group graph terminate
        # (a member_of b, b member_of a) instead of blowing the Python stack,
        # while still allowing a node to be revisited via a *stronger* path.
        start = subject.strip().lower()
        frontier = [(start, AttenuationLevel.L4_SOVEREIGN_ENCLAVE)]
        best_budget: Dict[str, int] = {}
        best: Optional[AttenuationLevel] = None

        while frontier:
            current, budget = frontier.pop()
            seen = best_budget.get(current)
            if seen is not None and seen >= rank(budget):
                continue
            best_budget[current] = rank(budget)

            # A direct grant, or a wildcard grant on the relation.
            for key in ((current, clean_rel, clean_obj), (current, clean_rel, "*")):
                granted = grants.get(key)
                if granted is None:
                    continue
                reachable = granted if rank(granted) < rank(budget) else budget
                if best is None or rank(reachable) > rank(best):
                    best = reachable

            # Transitive group membership, attenuated by the membership edge.
            for (s, r, o), level in grants.items():
                if s == current and r == "member_of":
                    onward = level if rank(level) < rank(budget) else budget
                    if best_budget.get(o, -1) < rank(onward):
                        frontier.append((o, onward))

        return best

    def check(self, subject: str, relation: str, object_resource: str) -> bool:
        """
        Evaluates whether a subject possesses a specific relation to an object resource.
        Defeats OWASP ASI03 Confused Deputy substring attacks via strict exact matching.
        """
        return self.effective_level(subject, relation, object_resource) is not None

    def authorize(
        self,
        subject: str,
        relation: str,
        object_resource: str,
        required_level: AttenuationLevel = AttenuationLevel.L2_STANDARD_OPERATOR,
        max_level: AttenuationLevel = AttenuationLevel.L4_SOVEREIGN_ENCLAVE,
    ) -> bool:
        """
        Validates authorization policy and checks that requested attenuation does not
        exceed the caller's ceiling or `max_level`.
        Raises AuthorizationDeniedError on refusal.
        """
        if self.ATTENUATION_RANK[required_level] > self.ATTENUATION_RANK[max_level]:
            raise AuthorizationDeniedError(
                f"Monotonic Attenuation Violation: Requested level {required_level} "
                f"exceeds maximum allowed attenuation of {max_level}."
            )

        # One evaluation answers both questions: whether any grant reaches this
        # object, and the ceiling of the strongest path that does. Asking the two
        # separately is what let an L4 grant elsewhere satisfy the ceiling test
        # for a resource it had no authority over.
        granted_level = self.effective_level(subject, relation, object_resource)
        if granted_level is None:
            raise AuthorizationDeniedError(
                f"Zanzibar ReBAC Refusal: Subject '{subject}' is not authorized to "
                f"'{relation}' on '{object_resource}'."
            )

        if self.ATTENUATION_RANK[required_level] > self.ATTENUATION_RANK[granted_level]:
            raise AuthorizationDeniedError(
                f"Monotonic Attenuation Violation: Subject '{subject}' may not hold "
                f"{required_level} on '{object_resource}'; the authority granted on "
                f"that resource ceilings at {granted_level}."
            )

        return True

    def issue_lease(
        self,
        subject: str,
        relation: str,
        object_resource: str,
        level: AttenuationLevel = AttenuationLevel.L2_STANDARD_OPERATOR,
        duration_seconds: float = 300.0,
    ) -> CapabilityLease:
        """
        Issues a cryptographically signed HMAC-SHA256 capability lease for authorized access.
        The requested level can never exceed the subject's authority ceiling.
        """
        self.authorize(subject, relation, object_resource, required_level=level)

        lease_id = str(uuid.uuid4())
        now = time.time()
        expires = now + duration_seconds

        signature = self._sign_lease(
            lease_id, subject, relation, object_resource, level.value, expires
        )

        return CapabilityLease(
            lease_id=lease_id,
            subject=subject,
            relation=relation,
            object_resource=object_resource,
            attenuation_level=level,
            granted_at=now,
            expires_at=expires,
            signature=signature,
        )

    def _sign_lease(
        self,
        lease_id: str,
        subject: str,
        relation: str,
        object_resource: str,
        level_value: str,
        expires: float,
    ) -> str:
        """
        Signs the lease fields with an unambiguous encoding.

        The fields may themselves contain colons, so joining them with ':' is
        ambiguous: a lease for the object `"public:admin_panel"` and one for the
        relation `"can_execute:public"` on object `"admin_panel"` would produce
        byte-identical signing input, letting one signature verify two different
        grants. Length-prefixing each field makes the encoding injective — no two
        distinct field tuples can produce the same bytes.
        """
        parts = (lease_id, subject, relation, object_resource, level_value, repr(expires))
        payload = b"".join(
            len(p.encode("utf-8")).to_bytes(4, "big") + p.encode("utf-8") for p in parts
        )
        return hmac.new(self._secret_key, payload, hashlib.sha256).hexdigest()

    def verify_lease(self, lease: CapabilityLease) -> bool:
        """
        Verifies the cryptographic integrity and expiration of a capability lease.

        Scope: this proves the lease was issued by this engine and has not been
        tampered with or expired. A lease is a bearer token — it is not single-use
        and there is no revocation before expiry, so a leaked lease remains
        usable for the remainder of its TTL. Keep `duration_seconds` short.
        """
        if not lease.is_valid:
            return False

        expected_sig = self._sign_lease(
            lease.lease_id,
            lease.subject,
            lease.relation,
            lease.object_resource,
            lease.attenuation_level.value,
            lease.expires_at,
        )
        return hmac.compare_digest(expected_sig, lease.signature)

    def _prune_consumed_leases(self, now: float) -> None:
        """Forgets redeemed lease ids once they expire. Caller must hold the lock.

        An expired lease is refused by `verify_lease` on its own, so keeping its
        id after that point protects nothing and would grow without bound.
        """
        for lease_id in [lid for lid, exp in self._consumed_leases.items() if exp <= now]:
            del self._consumed_leases[lease_id]

    def consume_lease(self, lease: CapabilityLease) -> bool:
        """
        Redeems a lease exactly once. Returns False if it is invalid or already used.

        `verify_lease` proves a lease is authentic and unexpired, which stops
        forgery but not replay: an attacker who captures a valid lease can present
        it repeatedly until its TTL runs out. Redeeming through this method records
        the lease id, so the second presentation is refused — the lease becomes a
        single-use capability.

        Use this for anything that should happen once (a transfer, a deployment, a
        privileged write). Use `verify_lease` when a capability is legitimately
        reusable for its lifetime, such as read access inside one session.

        The registry is in-process and in-memory, matching the rest of this
        runtime: it makes a lease single-use within the process that issued it, not
        across a cluster. Several replicas each need their own issuer, or a shared
        store the Enterprise edition provides.
        """
        now = time.time()
        # Prune first, and regardless of the outcome below: an invalid lease must
        # not be the thing that keeps expired ids in memory.
        with self._lock:
            self._prune_consumed_leases(now)

        if not self.verify_lease(lease):
            return False

        with self._lock:
            if lease.lease_id in self._consumed_leases:
                return False
            self._consumed_leases[lease.lease_id] = lease.expires_at
            return True

    @property
    def consumed_lease_count(self) -> int:
        """Number of redeemed, not-yet-expired lease ids being remembered."""
        with self._lock:
            self._prune_consumed_leases(time.time())
            return len(self._consumed_leases)
