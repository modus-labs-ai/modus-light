#!/usr/bin/env python3
"""
Example 05: Customer Test Drive — End-to-End Enterprise Scenario
================================================================
Simulates a real-world enterprise multi-agent pipeline:
1. Customer input sanitization via TokenShield.
2. Google Zanzibar ReBAC capability verification.
3. Pre-Dispatch Step 5 FinOps spend gate check.
4. Linda Tuple Space coordination between 2 workers.
5. Task completion, unshielding, and ROI summary.
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

from modus_light import ModusLight
from modus_light.token_meter import measure_token_reduction


def main():
    print("=" * 80)
    print("  🚀 MODUS LIGHT — FULL ENTERPRISE PIPELINE TEST DRIVE")
    print("=" * 80)

    # 1. Initialize Runtime
    rt = ModusLight(tenant_id="acme_logistics", spend_cap_tokens=5000)

    # 2. Ingest confidential customer shipment order containing PII
    raw_order = (
        "Customer john.doe@example.com authorized release of cargo #84920 "
        "to secure facility at 10.0.4.15 using gateway token sk-ant-live-9382019482019482."
    )
    print("\n1. INGESTING RAW UNTRUSTED CUSTOMER ORDER:")
    print("  ", raw_order)

    # 3. Apply TokenShield Lite (0 wire tokens consumed)
    shielded_order, token_map = rt.shield_prompt(raw_order)
    print("\n2. TOKENSHIELD RESULT (Zero External LLM Tokens):")
    print("   Shielded Prompt:", shielded_order)
    print("   Private Token Map:", token_map)

    # 4. Authorize Dispatcher Agent via ReBAC & FinOps
    print("\n3. AUTHORIZING DISPATCHER WORKER:")
    # Settle through the handle authorize_step returns, so the reservation it
    # took against the cap is actually released rather than left holding budget.
    reservation = rt.authorize_step(role="admin", sector="logistics", estimated_tokens=150)
    # The saving reported in the summary below is MEASURED, not declared: the
    # meter builds the prompts a conversational run and a tuple-space run would
    # each send for this same pipeline, and counts them. An ROI line is only
    # worth reading if the number behind it was counted rather than chosen.
    comparison = measure_token_reduction()
    rt.commit_spend(
        actual_tokens=150, tokens_saved=comparison.tokens_saved, reservation=reservation
    )
    print("   ✓ ReBAC Role 'admin' validated for 'logistics'.")
    print("   ✓ Step 5 Spend Kill Switch approved 150 token budget.")

    # 5. Emit Linda Task Tuple to Shared Coordination Space
    print("\n4. DISPATCHING TASK TUPLE TO SPACE:")
    task = rt.submit_task(
        topic="process_cargo_clearance",
        payload={"sanitized_order": shielded_order, "priority_tier": "EXPEDITED"},
        priority=5
    )
    print(f"   ✓ Task #{task.id} queued. Status: {task.status}")

    # 6. Worker Node claims task without chat history wire bloat
    print("\n5. WORKER NODE EXECUTION:")
    worker_task = rt.claim_task(worker_id="warehouse_robot_alpha", topic="process_cargo_clearance")
    if worker_task is None:
        raise SystemExit("FAILED: no tuple was claimable on 'process_cargo_clearance'")
    print(f"   ✓ Leased to '{worker_task.lease_owner}'.")

    # Simulate worker producing verified manifest
    execution_result = {
        "clearance_code": "CLEAR-2026-X99",
        "customs_duty_paid": True,
        "facility_status": "READY"
    }
    # Passing worker_id has the lease enforced: only the holder may close the task out.
    # Deliberately not an `assert` — `python -O` strips the whole statement, which
    # would drop the call itself and still print the success line below.
    done = rt.complete_task(worker_task.id, execution_result, worker_id="warehouse_robot_alpha")
    if not done:
        raise SystemExit("completion refused: the lease is not held by this worker")
    print("   ✓ Task executed and completed.")

    # 7. Restore original entities for final audit report
    print("\n6. RECONSTRUCTING SANITIZED DATA (UNSHIELDING):")
    restored = rt.unshield_text(shielded_order, token_map)
    if restored != raw_order:
        raise SystemExit(
            "FAILED: the unshielded payload is not byte-identical to the original, "
            "so the masking round-trip lost or altered data."
        )
    print("   ✓ Original confidential payload verified byte-identical.")

    # 8. Enterprise ROI Summary
    summary = rt.finops.get_finops_summary()
    print("\n" + "=" * 80)
    print("  📊 TEST DRIVE TELEMETRY & ROI SUMMARY")
    print("=" * 80)
    print(f"  Total API Wire Tokens Consumed:   {summary['consumed_tokens']} tokens")
    # Computed from the two figures printed above, not a fixed headline number:
    # the saving is only ever as large as this run's own telemetry shows.
    saved = summary["tokens_saved_estimate"]
    print(f"  Measured Tokens Saved vs Chat:    {saved} tokens "
          f"({comparison.reduction_pct:.0f}% reduction over {comparison.hops} hops)")
    print(f"    ↳ conversational replay would send {comparison.conversational_tokens:,} tokens "
          f"for this pipeline;")
    print(f"      tuple-space handoff sends {comparison.tuple_space_tokens:,}. "
          f"Run `modus-light tokens` for")
    print("      the full curve — the saving grows with pipeline length, so a short")
    print("      pipeline like this one saves the least.")
    print(f"  Overdraft / Budget Violations:    ${summary['overdraft_amount']:.2f}")
    print("  Zero-Token Local Memory Bus:      ACTIVE")
    print("=" * 80)
    print("\nReady to deploy on bare-metal air-gapped appliances? "
          "See: https://github.com/modus-labs-ai/modus-light\n")


if __name__ == "__main__":
    main()
