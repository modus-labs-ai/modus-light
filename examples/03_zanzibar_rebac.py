#!/usr/bin/env python3
"""
Example 03: Google Zanzibar ReBAC & Monotonic Attenuation
=========================================================
Demonstrates relationship-based authorization, confused deputy attack prevention,
and cryptographically signed HMAC capability leases.
"""
import sys
from pathlib import Path

# Add src to sys.path so examples run immediately without prior pip install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# The status glyphs below are non-ASCII. On a stream that cannot encode them —
# cp1252 on Windows when output is redirected to a file, or an explicit
# PYTHONIOENCODING=ascii — printing would raise UnicodeEncodeError and lose the
# exit status. Degrade the glyph instead of failing the run.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from modus_light import ModusLight, AttenuationLevel, AuthorizationDeniedError


def main():
    rt = ModusLight(tenant_id="bank_enclave")

    # 1. Define custom enterprise relations
    # "alice" is an analyst in risk_mgmt
    rt.rebac.add_relation("alice", "member_of", "risk_analysts")
    rt.rebac.add_relation("risk_analysts", "can_execute", "fraud_detection")

    print("Checking authorization for 'alice' on 'fraud_detection'...")
    # Not `assert`: `python -O` strips assert statements, so the check would
    # disappear while the success message below still printed.
    if not rt.rebac.check("alice", "can_execute", "fraud_detection"):
        raise SystemExit(
            "FAILED: alice should inherit can_execute on fraud_detection through "
            "her risk_analysts membership, but the check refused her."
        )
    print("✓ Granted: Alice transitively inherited permission via 'risk_analysts'.")

    # 2. Confused Deputy Attack (OWASP ASI03)
    print("\nSimulating Confused Deputy Attack: 'guest_attacker_admin' attempting 'fraud_detection'...")
    try:
        rt.authorize_step("guest_attacker_admin", "fraud_detection")
        raise SystemExit(
            "FAILED: 'guest_attacker_admin' was authorized on 'fraud_detection'. "
            "A substring-shaped subject name must not satisfy an exact tuple match."
        )
    except AuthorizationDeniedError as err:
        print("✓ Attack Defeated: ReBAC exact tuple matching blocked rogue caller.")
        print(f"  --> {err}")

    # 3. Issue a Cryptographic HMAC Capability Lease
    print("\nIssuing 5-minute Capability Lease for Alice at L2_STANDARD_OPERATOR...")
    lease = rt.issue_capability_lease(
        subject="alice",
        relation="can_execute",
        object_resource="fraud_detection",
        level=AttenuationLevel.L2_STANDARD_OPERATOR,
        duration_seconds=300
    )
    print(f"✓ Lease Issued: ID={lease.lease_id}")
    print(f"  Level:      {lease.attenuation_level.value}")
    print(f"  Signature:  {lease.signature[:16]}... (HMAC-SHA256)")
    print(f"  Valid:      {lease.is_valid}")

    # 4. Redeem the lease once, then replay it
    print("\nRedeeming the lease for a one-time privileged action...")
    if not rt.redeem_capability_lease(lease):
        raise SystemExit(
            "FAILED: a freshly issued, valid lease could not be redeemed."
        )
    print("✓ First redemption accepted")

    # A captured lease stays signature-valid for the whole of its TTL, so a
    # signature check alone would accept this replay. Redemption spends the lease.
    if rt.redeem_capability_lease(lease):
        raise SystemExit(
            "FAILED: the same lease was redeemed twice — replay was not refused."
        )
    print("✓ Replay refused: the lease is single-use once redeemed")
    print(f"  Signature still valid: {rt.rebac.verify_lease(lease)} "
          f"(authentic, but already spent)")

    # 5. Verify Monotonic Attenuation (cannot escalate above L2)
    print("\nAttempting monotonic privilege escalation to L4_SOVEREIGN_ENCLAVE...")
    try:
        rt.rebac.authorize(
            subject="alice",
            relation="can_execute",
            object_resource="fraud_detection",
            required_level=AttenuationLevel.L4_SOVEREIGN_ENCLAVE,
            max_level=AttenuationLevel.L2_STANDARD_OPERATOR
        )
        raise SystemExit(
            "FAILED: alice was allowed to hold L4_SOVEREIGN_ENCLAVE above her "
            "L2 ceiling — monotonic attenuation was not enforced."
        )
    except AuthorizationDeniedError:
        print("✓ Escalation Denied: Subagents cannot exceed parent authority ceiling.")


if __name__ == "__main__":
    main()
