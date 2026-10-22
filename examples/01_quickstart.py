#!/usr/bin/env python3
"""
Example 01: Quickstart
======================
Demonstrates the basic usage of Modus Light in under 15 lines of code.
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


def main():
    # 1. Initialize sovereign runtime
    rt = ModusLight(tenant_id="fintech_corp", spend_cap_tokens=10000)

    # 2. Zero-Cost TokenShield entity masking (0 LLM wire tokens)
    clean_prompt, token_map = rt.shield_prompt("Send Q3 payroll report to cfo@example.com at 192.168.1.42")
    print("Shielded Prompt:", clean_prompt)
    # Output: "Send Q3 payroll report to <TOKEN_EMAIL_0> at <TOKEN_IP_1>"

    # 3. Zanzibar ReBAC Authorization & FinOps Spend Check.
    # authorize_step returns the spend reservation it took against the cap. Settle
    # it with commit_spend(reservation=...) once the step is done, or release it if
    # the step is abandoned — an unsettled reservation keeps holding budget.
    reservation = rt.authorize_step(role="admin", sector="finance", estimated_tokens=120)
    print("✓ Authorization and FinOps pre-dispatch checks passed.")

    # The real step would run here; it actually used 96 tokens.
    rt.commit_spend(actual_tokens=96, reservation=reservation)

    # 4. Decoupled Linda coordinate task dispatch
    task = rt.submit_task(topic="payroll_reconciliation", payload={"quarter": "2026-Q3"})
    print(f"✓ Task Queued: ID={task.id}, Topic='{task.topic}', Status='{task.status}'")


if __name__ == "__main__":
    main()
