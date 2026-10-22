#!/usr/bin/env python3
"""
Example 02: Pre-Dispatch Step 5 FinOps Kill Switch
==================================================
Demonstrates how Modus Light prevents catastrophic runaway token spend
BEFORE committing tokens to frontier LLMs, so a refused step spends nothing.
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

from modus_light import ModusLight, SpendCapExceededError
from modus_light.token_meter import measure_token_reduction


def main():
    # Set a strict budget ceiling of 500 tokens
    rt = ModusLight(tenant_id="startup_team", spend_cap_tokens=500)
    print("Initial FinOps State:", rt.finops.get_finops_summary())

    # Step 1: Normal step within budget (200 tokens)
    reservation = rt.authorize_step(role="admin", sector="engineering", estimated_tokens=200)
    # `tokens_saved` is operator-supplied telemetry, so supply a measured number:
    # what a conversational replay of the same pipeline would have cost on the
    # wire, minus what the tuple space actually sends. See `modus-light tokens`.
    rt.commit_spend(
        actual_tokens=200,
        tokens_saved=measure_token_reduction().tokens_saved,
        reservation=reservation,
    )
    print("✓ Step 1 approved and executed (200 tokens consumed).")
    print("Remaining budget:", rt.finops.remaining_budget)

    # Step 2: Attempt a rogue recursive loop requesting 400 tokens
    print("\nAttempting recursive agent step requesting 400 tokens (Budget: 300)...")
    try:
        rt.authorize_step(role="admin", sector="engineering", estimated_tokens=400)
        # Reached only if the kill switch failed to trip. Exit non-zero: this file
        # runs in CI, and an example that narrates a breach and then exits 0 leaves
        # the pipeline green.
        raise SystemExit(
            "FAILED: the spend cap was exceeded without refusal — the kill switch "
            "did not trip on a 400-token step against a 300-token remaining budget."
        )
    except SpendCapExceededError as err:
        print("✓ Step 5 Spend Kill Switch intercepted overspend:")
        print(f"  --> {err}")

    # Summary
    summary = rt.finops.get_finops_summary()
    print("\nFinal FinOps Telemetry:")
    print(f"  Consumed:          {summary['consumed_tokens']} tokens")
    print(f"  Remaining:         {summary['remaining_tokens']} tokens")
    print(f"  Overdraft Enforced: ${summary['overdraft_amount']:.2f}")


if __name__ == "__main__":
    main()
