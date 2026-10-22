"""
Modus Light — Interactive Command Line Interface (CLI)
======================================================
Provides interactive test drives, security audits, and capability benchmarks.
"""

import argparse
import os
import sys
import time
from typing import Callable, List, Optional, Tuple
from . import __version__
from .client import ModusLight
from .types import ActorSpec, AttenuationLevel
from .exceptions import AuthorizationDeniedError, SpendCapExceededError

# ANSI terminal colors. Blanked by `_configure_output()` when the destination is
# not a terminal, so piping into a log or a file yields readable text instead of
# escape sequences.
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _configure_output() -> None:
    """Make the CLI's output safe for terminals that are not a UTF-8 TTY.

    Two independent hazards, both reported by users rather than by CI:

    1. **Encoding.** The status glyphs are non-ASCII, and `cp1252` — what
       Windows still uses for a redirected stream — cannot encode them. The
       package advertises `Operating System :: OS Independent`, so
       `modus-light audit > audit.log` on Windows must not die with a
       `UnicodeEncodeError` after the audit has already passed. Linux is
       normally spared by PEP 538/540 locale coercion, but an explicit
       `PYTHONIOENCODING=ascii` defeats that too. Degrading a glyph to `?` is
       acceptable; losing the exit status to a traceback is not.
    2. **Colour.** ANSI codes belong on a terminal. When stdout is a pipe, a
       file, or a dumb terminal — or the user has set `NO_COLOR` — they are
       noise that breaks log greps.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                # A caller may have replaced the stream with something that
                # cannot be reconfigured; printing must still work.
                pass

    use_color = (
        hasattr(sys.stdout, "isatty")
        and sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM") != "dumb"
    )
    if not use_color:
        global CYAN, GREEN, YELLOW, RED, BOLD, DIM, RESET
        CYAN = GREEN = YELLOW = RED = BOLD = DIM = RESET = ""


def banner():
    print(f"""


{CYAN}{BOLD}================================================================================
  🛡️  MODUS LIGHT — SOVEREIGN ENTERPRISE AGENT RUNTIME
  Community Edition (BSL 1.1) • Zero-Token State • Google Zanzibar ReBAC
================================================================================{RESET}""")


def run_demo():
    """
    Interactive 6-Step Customer Test Drive:
    Guides the user through every core capability without requiring any cloud API keys.
    """
    banner()
    print(f"{BOLD}Welcome to the Modus Light Free Customer Test Drive!{RESET}")
    print(f"{DIM}Running completely in-process with 0 external cloud dependencies.{RESET}\n")

    # The demo needs a low ceiling for step 3 to be able to trip the kill switch,
    # but passing it explicitly would override MODUS_SPEND_CAP_TOKENS and make the
    # documented variable look like it does nothing. So: honour the environment
    # when it is set, and fall back to the demo ceiling when it is not.
    demo_cap = int(os.environ["MODUS_SPEND_CAP_TOKENS"]) if os.environ.get(
        "MODUS_SPEND_CAP_TOKENS", "").strip().isdigit() else 1000
    rt = ModusLight(spend_cap_tokens=demo_cap)

    # Step 1: TokenShield
    print(f"{CYAN}{BOLD}[Step 1/6] TokenShield Zero-Cost Entity Sanitization{RESET}")
    raw_prompt = "Contact admin@example.com at 192.0.2.10 with secret sk-ant-live-4938201948201948"
    print(f"  {DIM}Input Prompt:{RESET}  {raw_prompt}")
    masked, token_map = rt.shield_prompt(raw_prompt)
    print(f"  {GREEN}Masked Prompt:{RESET} {masked}")
    print(f"  {DIM}Token Map:{RESET}     {token_map}")
    print(f"  {GREEN}✓ PII sanitized locally. 0 LLM wire tokens consumed.{RESET}\n")
    time.sleep(0.3)

    # Step 2: ReBAC Authorization
    print(f"{CYAN}{BOLD}[Step 2/6] Google Zanzibar ReBAC & Confused Deputy Defense{RESET}")
    print(f"  {DIM}Testing role:{RESET} 'guest_attacker_admin' attempting 'cyber_defense' sector...")
    try:
        rt.authorize_step("guest_attacker_admin", "cyber_defense", 50)
        # Exit non-zero rather than printing a failure and continuing: this demo
        # is one of the gates in `make verify`, and a narrated breach that still
        # returns 0 leaves the pipeline green.
        raise SystemExit(
            "FAILED: 'guest_attacker_admin' was admitted to the 'cyber_defense' "
            "sector. Exact tuple matching is not holding."
        )
    except AuthorizationDeniedError as e:
        print(f"  {GREEN}✓ Refused:{RESET} {e}")
        print(f"  {GREEN}✓ OWASP ASI03 Confused Deputy attack blocked at the authorization gate.{RESET}\n")
    time.sleep(0.3)

    # Step 3: Pre-Dispatch Step 5 FinOps Kill Switch
    print(f"{CYAN}{BOLD}[Step 3/6] Pre-Dispatch Step 5 FinOps Spend Kill Switch{RESET}")
    # Sized against the live remaining budget rather than a fixed 2,500, so the
    # step is guaranteed to breach whatever ceiling this run is actually using.
    remaining = rt.finops.remaining_budget
    rogue_request = remaining + 1500
    print(f"  {DIM}Remaining budget:{RESET} {remaining:,} tokens. "
          f"Attempting rogue loop requesting {rogue_request:,} tokens...")
    try:
        rt.authorize_step("admin", "cyber_defense", estimated_tokens=rogue_request)
        raise SystemExit(
            f"FAILED: a {rogue_request}-token step was authorized with only "
            f"{remaining} tokens remaining. The pre-dispatch kill switch did not trip."
        )
    except SpendCapExceededError as e:
        print(f"  {GREEN}✓ Refused:{RESET} {e}")
        # The dollar figure is read back from telemetry, not asserted: a refused
        # step spends nothing, and this prints whatever the gateway measured.
        overdraft = rt.finops.get_finops_summary()["overdraft_amount"]
        print(f"  {GREEN}✓ Runaway loop halted before API dispatch "
              f"(measured overdraft: ${overdraft:.2f}).{RESET}\n")
    time.sleep(0.3)

    # Step 4: Linda Tuple Space Coordination
    print(f"{CYAN}{BOLD}[Step 4/6] Decoupled Linda Tuple Space (Zero-Token Coordination){RESET}")
    task = rt.submit_task("reconcile_gl_accounts", {"ledger_id": "GL-2026-Q3", "amount": 142500.00}, priority=10)
    print(f"  {DIM}Task Emitted:{RESET} ID={task.id}, Topic='{task.topic}', Priority={task.priority}")
    claimed = rt.claim_task("worker_node_1", topic="reconcile_gl_accounts")
    if claimed is None:
        # Reported rather than dereferenced: an unclaimable tuple must not crash the demo.
        print(f"  {YELLOW}! No tuple was claimable for this topic.{RESET}\n")
    else:
        print(f"  {GREEN}✓ Task Leased:{RESET} Worker='{claimed.lease_owner}', Status='{claimed.status}'")
        # Completion is lease-checked, so the printout below reports the real
        # result rather than assuming success.
        done = rt.complete_task(
            claimed.id, {"balanced": True, "delta": 0.00}, worker_id="worker_node_1"
        )
        if done:
            print(f"  {GREEN}✓ Task Completed over the in-process bus. 0 wire tokens exchanged.{RESET}\n")
        else:
            print(f"  {YELLOW}! Completion refused: the lease is not held by this worker.{RESET}\n")
    time.sleep(0.3)

    # Step 5: OTP-pattern Supervisor Resilience
    print(f"{CYAN}{BOLD}[Step 5/6] OTP Supervisor Actor Recovery & Circuit Breaker{RESET}")
    attempts = {"count": 0}

    def flaky_worker():
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("Simulated Database Socket Duress")
        return "recovered"

    rt.supervisor.register_actor(
        ActorSpec(name="db_agent", role="database_writer", restart_policy="transient"),
        flaky_worker
    )
    print(f"  {DIM}Executing actor 'db_agent' under supervisor tree...{RESET}")
    try:
        outcome = rt.supervisor.execute_actor("db_agent")
        print(f"  {GREEN}✓ Restarted in place and returned: {outcome}{RESET}")
    except Exception as e:
        print(f"  {RED}FAILED:{RESET} {e}")
    time.sleep(0.3)

    def broken_worker():
        raise RuntimeError("Permanent Storage Fault")

    rt.supervisor.register_actor(
        ActorSpec(name="ledger_agent", role="database_writer", restart_policy="transient", max_restarts=2),
        broken_worker
    )
    try:
        rt.supervisor.execute_actor("ledger_agent")
        raise SystemExit(
            "FAILED: a permanently crashing actor ran to completion. The "
            "supervisor did not contain the crash loop."
        )
    except Exception as e:
        print(f"  {GREEN}✓ Panic Isolated:{RESET} {e}")
        print(f"  {GREEN}✓ Supervisor contained the crash loop and tripped the circuit breaker.{RESET}\n")
    time.sleep(0.3)

    # Step 6: Health Telemetry & Enterprise Roadmap
    print(f"{CYAN}{BOLD}[Step 6/6] Runtime Telemetry & Enterprise Upgrade Readiness{RESET}")
    health = rt.check_health()
    # DEGRADED is the correct reading here, not a defect: Step 5 deliberately
    # crash-looped `ledger_agent` until the breaker tripped, and a runtime that
    # reported RUNNING with a tripped actor would be the thing worth worrying
    # about. Say so, so the demo does not end on an unexplained red word.
    status_note = ""
    if health["status"] != "RUNNING":
        status_note = f"  {DIM}(expected — 'ledger_agent' was crash-looped in Step 5){RESET}"
    print(f"  Status:             {GREEN}{health['status']}{RESET}{status_note}")
    print(f"  Edition:            {health['runtime_edition']}")
    print(f"  Coordination Bus:   {health['coordination_bus']} (no network transport)")
    print(f"  Wire Tokens Used:   {health['wire_tokens_consumed']}")
    print(f"  Air-Gap Verified:   {health['air_gap_compliant']} (no network imports in package)")
    print(f"  Actor Health:       {health['actors']['status_map']}\n")

    print(f"{BOLD}🎉 Test Drive Completed Successfully!{RESET}")
    print("Ready for Enterprise scale (Air-gapped NUMA appliance, H100 GPUs, RAID 10 NVMe, 22-Sector JIT)?")
    print(f"See: {CYAN}https://github.com/modus-labs-ai/modus-light{RESET} or run {BOLD}modus-light info{RESET}.\n")


def run_benchmark():
    """
    Runs the 10 capability benchmarks.

    Every vector is an executable assertion against this runtime. Numbers shown
    are measured locally; nothing about other frameworks is asserted here.
    """
    banner()
    print(f"  {BOLD}⚔️  MODUS LIGHT — CAPABILITY BENCHMARK RUNNER{RESET}\n")
    t0 = time.perf_counter()
    rt = ModusLight(spend_cap_tokens=1000)

    vectors = CAPABILITY_VECTORS

    failures = 0
    for label, vector in vectors:
        try:
            detail = vector(rt)
            print(f"  [{GREEN}PASS{RESET}] {label}: {detail}")
        except Exception as exc:
            failures += 1
            print(f"  [{RED}FAIL{RESET}] {label}: {exc}")

    elapsed = time.perf_counter() - t0
    print("-" * 80)
    passed = len(vectors) - failures
    if failures:
        print(f"  {RED}{BOLD}✗ {passed}/{len(vectors)} CAPABILITY VECTORS PASSED ({elapsed:.4f}s){RESET}")
    else:
        print(f"  {GREEN}{BOLD}🎉 {passed}/{len(vectors)} CAPABILITY VECTORS PASSED ({elapsed:.4f}s){RESET}")
    print("=" * 80 + "\n")
    return failures


def _bench_tuple_bus(rt) -> str:
    task = rt.submit_task("bench_task", {"payload": "x"}, priority=1)
    claimed = rt.claim_task("bench_worker", topic="bench_task")
    if claimed is None or claimed.id != task.id:
        raise AssertionError("tuple was not routed to the worker")
    if not rt.complete_task(claimed.id, {"ok": True}, worker_id="bench_worker"):
        raise AssertionError("the lease holder was refused completion of its own tuple")
    return "1 tuple routed in-process, 0 network calls"


def _bench_linda_order(rt) -> str:
    rt.submit_task("bench_q", {"n": "low"}, priority=1)
    crit = rt.submit_task("bench_q", {"n": "critical"}, priority=100)
    first = rt.claim_task("bench_worker", topic="bench_q")
    if first is None or first.id != crit.id:
        raise AssertionError("priority order violated")
    return "highest priority served first, FIFO within a priority"


def _bench_rebac_denial(rt) -> str:
    try:
        rt.authorize_step("guest_attacker_admin", "cyber_defense")
    except AuthorizationDeniedError:
        return "unauthorized subject refused (fail-closed)"
    raise AssertionError("unauthorized subject was admitted")


def _bench_supervisor_restart(rt) -> str:
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("transient fault")
        return "recovered"

    rt.supervisor.register_actor(ActorSpec(name="bench_actor", role="worker"), flaky)
    result = rt.supervisor.execute_actor("bench_actor")
    if result != "recovered":
        raise AssertionError("actor did not recover")
    return f"crash isolated, restarted after {attempts['count']} attempts"


#: Upper bound the dispatch vector is allowed to report. Deliberately far above
#: the figure the docs quote (~0.002 ms median on commodity hardware): this gate
#: exists to catch an algorithmic regression — a dispatch that started scanning
#: the queue — not to assert one machine's clock speed on every other machine.
#: A tight absolute bound here would simply flake on slower or loaded CI runners.
DISPATCH_BUDGET_MS = 0.05


def _bench_staging_latency(rt) -> str:
    # The round trip is timed first, on the space as it stands, so that the
    # backlog this vector plants below cannot inflate it. Claiming a tuple scans
    # for the best candidate, so a round trip measured behind 2,000 queued tuples
    # is a different measurement — reported separately rather than conflated.
    round_trips = []
    for i in range(200):
        t0 = time.perf_counter()
        task = rt.submit_task("bench_latency", {"n": i})
        rt.claim_task("bench_worker", topic="bench_latency")
        if not rt.complete_task(task.id, {"ok": True}, worker_id="bench_worker"):
            raise AssertionError("stage+claim+complete did not close the tuple out")
        round_trips.append((time.perf_counter() - t0) * 1000)
    round_trips.sort()
    round_trip_ms = round_trips[len(round_trips) // 2]

    # Dispatch is then timed on its own against a populated queue, because that
    # is the claim worth defending: enqueueing work must not get slower as the
    # backlog grows. Timing it on an empty space would hide exactly that.
    for i in range(2000):
        rt.submit_task("bench_backlog", {"i": i})

    samples = []
    for i in range(2000):
        t0 = time.perf_counter()
        rt.submit_task("bench_dispatch", {"i": i})
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    median_ms = samples[len(samples) // 2]
    p95_ms = samples[int(0.95 * len(samples))]
    if median_ms > DISPATCH_BUDGET_MS:
        raise AssertionError(
            f"dispatch median {median_ms:.4f} ms exceeds the "
            f"{DISPATCH_BUDGET_MS} ms budget — dispatch is no longer constant-time"
        )

    return (
        f"dispatch {median_ms:.4f} ms median / {p95_ms:.4f} ms p95 under a "
        f"2,000-tuple backlog; stage+claim+complete round trip "
        f"{round_trip_ms:.4f} ms median (all measured, in-process)"
    )


def _bench_finops_kill(rt) -> str:
    try:
        rt.authorize_step("admin", "cyber_defense", estimated_tokens=2000)
    except SpendCapExceededError:
        return "over-cap dispatch refused before any provider call"
    raise AssertionError("overspend was allowed")


def _bench_capability_lease(rt) -> str:
    rt.rebac.add_relation("bench_auditor", "can_execute", "finance")
    lease = rt.issue_capability_lease(
        "bench_auditor", "can_execute", "finance", level=AttenuationLevel.L2_STANDARD_OPERATOR
    )
    if not rt.rebac.verify_lease(lease):
        raise AssertionError("lease signature did not verify")
    lease.subject = "attacker"
    if rt.rebac.verify_lease(lease):
        raise AssertionError("tampered lease passed verification")
    return "HMAC-SHA256 lease verified, tampering detected"


def _bench_injection_filter(rt) -> str:
    masked, _ = rt.shield_prompt("invoice\u200B and \u202Eoverride attempt")
    if "\u200B" in masked or "\u202E" in masked:
        raise AssertionError("invisible control characters survived")
    return "zero-width and bidi controls neutralized"


def _bench_homoglyph(rt) -> str:
    masked, _ = rt.shield_prompt("pаyment request")  # Cyrillic а
    if "pаyment" in masked:
        raise AssertionError("homoglyph survived folding")
    return "Cyrillic/Greek homoglyphs folded to ASCII"


def _bench_airgap_hygiene(rt) -> str:
    if not rt.network_free():
        raise AssertionError("package imports a network transport")
    symlinks = rt.package_symlink_count()
    if symlinks:
        raise AssertionError(f"{symlinks} symlink(s) in the installed package")
    return "0 network transports imported, 0 symlinks"


def run_audit() -> bool:
    """
    Runs the compliance smoke audit and returns True only when it passed.

    The return value is what the caller turns into an exit status, so a FAILED
    audit can fail `make verify` and a customer's CI pipeline. Printing a verdict
    while always exiting 0 made the compliance gate of a security product
    incapable of failing.
    """
    banner()
    rt = ModusLight()
    report = rt.run_smoke_audit()
    # Colour follows the result rather than being hard-coded green, so a partial
    # pass does not read as a clean one at a glance.
    ok = report.status == "PASSED" and not report.findings
    verdict_colour = GREEN if ok else RED
    print(f"  Timestamp:         {report.timestamp}")
    print(
        f"  Checks:            {verdict_colour}{report.checks_passed}/{report.checks_total} "
        f"PASSED{RESET}"
    )
    print(f"  Duration:          {report.duration_seconds}s")
    print(f"  Wire Tokens Used:  {report.wire_tokens_consumed} (no provider call in the audit)")
    print(f"  Symlinks Detected: {report.symlink_count}")
    print(f"  Status:            {verdict_colour}{BOLD}{report.status}{RESET}")
    if report.findings:
        print(f"  {RED}{BOLD}Findings:{RESET}")
        for finding in report.findings:
            print(f"    - {finding}")
    print()
    return ok


def show_info():
    """Displays architecture overview and Light vs Enterprise matrix."""
    banner()
    print(f"""


{BOLD}MODUS LIGHT (COMMUNITY) VS. MODUS ZEN OS (ENTERPRISE){RESET}

| Capability / Dimension           | Modus Light (Community)   | Modus Zen OS (Enterprise)     |
|:---------------------------------|:-------------------------:|:-----------------------------:|
| License                          | BSL 1.1 (Source-Available)| Enterprise Commercial         |
| TokenShield Entity Masking       | ✓ Included (Standard)     | ✓ Enterprise + Custom Models  |
| Step 5 FinOps Spend Kill Switch  | ✓ Included                | ✓ Multi-Tenant Spend Quotas   |
| Google Zanzibar ReBAC            | ✓ In-Memory Tuples        | ✓ Distributed ReBAC + FTS5    |
| Linda Tuple Space Coordination   | ✓ In-Memory Tuple Space   | ✓ DBOS Transactional NVMe WAL |
| OTP Actor Supervision            | ✓ Python One-For-One      | ✓ Production OTP Mesh Engine  |
| Hardware Appliance Sizing        | Single Node / Developer   | Dual NUMA AMD EPYC / Xeon     |
| GPU Neural Inference Mesh        | User GPU / CPU            | 4x–8x H100/L40S (384GB VRAM)  |
| Durable WAL Storage              | In-Memory / Local SSD     | Hardware RAID 10 NVMe         |
| Ephemeral JIT Toolkit            | Staging Interface         | 22-Sector WASI RAM-Disk       |
| Multi-Channel C2 Quorum          | In-Process HMAC           | Signal, Telegram, WhatsApp C2 |
| Probabilistic AI Forecasting     | Heuristic Arbitrage       | TimesFM 3-Tier Quantiles      |
| SLA & Support                    | Community / GitHub Issues | 99.999% HA · 15-Min P1 SLA    |

{DIM}Enterprise appliance sizing or a turnkey pilot: https://github.com/modus-labs-ai/modus-light/issues{RESET}
""")


#: The capability vectors the benchmark runs. A module constant rather than a
#: local, so `tests/test_docs.py` can check that the count the README advertises
#: is the count that actually executes. Each vector receives the live runtime and
#: returns the measurement it made.
CAPABILITY_VECTORS: List[Tuple[str, Callable[["ModusLight"], str]]] = [
    ("W7.1 Zero-wire tuple coordination", _bench_tuple_bus),
    ("W7.2 Linda priority + FIFO routing", _bench_linda_order),
    ("W7.3 ReBAC fail-closed kernel gate", _bench_rebac_denial),
    ("W7.4 Supervisor panic isolation + restart", _bench_supervisor_restart),
    ("W7.5 Ephemeral staging latency", _bench_staging_latency),
    ("W7.6 FinOps Step 5 spend kill switch", _bench_finops_kill),
    ("W7.7 HMAC capability lease custody", _bench_capability_lease),
    ("W7.8 Unicode prompt-injection pre-filter", _bench_injection_filter),
    ("W7.9 Homoglyph evasion neutralization", _bench_homoglyph),
    ("W7.10 Air-gap & symlink hygiene", _bench_airgap_hygiene),
]


#: The hop counts the published token-reduction table reports. Kept here so the
#: docs test can assert the README quotes this measurement and not a memory of it.
TOKEN_REPORT_HOPS = (5, 10, 20, 50, 100)


def run_token_report() -> int:
    """
    Measure the coordination token cost of both architectures and print the
    comparison.

    Nothing here is a stored constant: both prompt sequences are constructed and
    counted on the spot, under three independent counting methods, so the figure
    can be checked rather than believed.
    """
    from .token_meter import COUNTERS, DEFAULT_PIPELINE, measure_token_reduction

    print(f"\n{BOLD}{CYAN}{'=' * 78}{RESET}")
    print(f"{BOLD}  MEASURED TOKEN REDUCTION — conversational replay vs tuple-space handoff{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 78}{RESET}\n")
    print(f"  Workload: a {len(DEFAULT_PIPELINE)}-stage pipeline, repeated to lengthen it.")
    print("  Both runs do identical work. Only the context each hop receives differs.\n")

    header = f"  {'hops':>5}  {'conversational':>15}  {'tuple space':>12}  {'saved':>9}  {'reduction':>10}"
    print(f"{BOLD}{header}{RESET}")
    print(f"  {'-' * 5}  {'-' * 15}  {'-' * 12}  {'-' * 9}  {'-' * 10}")

    measured = []
    for hops in TOKEN_REPORT_HOPS:
        repeats = max(1, hops // len(DEFAULT_PIPELINE))
        result = measure_token_reduction(repeats=repeats)
        measured.append(result)
        print(
            f"  {result.hops:>5}  {result.conversational_tokens:>15,}  "
            f"{result.tuple_space_tokens:>12,}  {result.tokens_saved:>9,}  "
            f"{GREEN}{result.reduction_pct:>9.1f}%{RESET}"
        )

    per_hop = measured[-1].tuple_space_tokens / measured[-1].hops
    print(f"\n  {BOLD}Why the saving grows:{RESET} the tuple-space column is linear — a flat")
    print(f"  {per_hop:.0f} tokens per hop at every length, because a hop is handed only the")
    print("  outputs it declared it needs. The conversational column is quadratic: hop n")
    print("  re-sends everything hops 1..n-1 already said. The handoff itself costs zero")
    print("  tokens in either direction, because it never reaches a model.\n")

    spreads = []
    for hops in TOKEN_REPORT_HOPS:
        repeats = max(1, hops // len(DEFAULT_PIPELINE))
        values = [measure_token_reduction(counter=name, repeats=repeats).reduction_pct for name in COUNTERS]
        spreads.append(max(values) - min(values))
    print(f"  {BOLD}Tokenizer independence:{RESET} re-counted under {len(COUNTERS)} different methods, the")
    print(f"  reduction moves by at most {max(spreads):.1f} percentage points — and by")
    print(f"  {max(spreads[2:]):.1f} points from 20 hops upward. The ratio is the claim, and the")
    print("  ratio does not depend on how you count.\n")

    short, long = measured[0], measured[-1]
    print(f"  {YELLOW}Read it honestly:{RESET} at {short.hops} hops the reduction is "
          f"{short.reduction_pct:.0f}%, not the")
    print(f"  {long.reduction_pct:.0f}% you get at {long.hops}. A short pipeline saves little, because there")
    print("  is little redundant history to avoid re-sending. The baseline is also the")
    print("  naive replay pattern: a framework that summarises history lands in between,")
    print("  and a pipeline where every hop truly needs every prior output cannot save")
    print("  anything at all. This runtime removes re-sent context, nothing more.\n")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """
    Entry point for the `modus-light` console script.

    `argv` defaults to the real command line; passing it explicitly lets the
    tests exercise the exit status a CI pipeline actually gates on, instead of
    only the functions behind it.
    """
    _configure_output()

    parser = argparse.ArgumentParser(
        prog="modus-light",
        description="Modus Light — Sovereign Enterprise Agent Runtime (Community Edition)"
    )
    # `--version` is the first thing anyone types to confirm what pip installed.
    parser.add_argument(
        "--version", action="version", version=f"modus-light {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("demo", help="Run the interactive 6-step customer test drive")
    subparsers.add_parser("benchmark", help="Run the 10 capability benchmarks")
    subparsers.add_parser("audit", help="Run the compliance smoke audit")
    subparsers.add_parser("info", help="Display architecture & Light vs Enterprise matrix")
    subparsers.add_parser("tokens", help="Measure token reduction vs conversational replay")

    shield_parser = subparsers.add_parser("shield", help="Shield text with TokenShield")
    shield_parser.add_argument("text", help="Text to shield")

    args = parser.parse_args(argv)

    if args.command == "benchmark":
        return 1 if run_benchmark() else 0
    if args.command == "demo" or args.command is None:
        run_demo()
        return 0
    if args.command == "audit":
        return 0 if run_audit() else 1
    if args.command == "tokens":
        return run_token_report()
    if args.command == "info":
        show_info()
        return 0
    if args.command == "shield":
        rt = ModusLight()
        masked, tmap = rt.shield_prompt(args.text)
        print(f"{CYAN}Original:{RESET} {args.text}")
        print(f"{GREEN}Masked:{RESET}   {masked}")
        print(f"{DIM}Mapping:{RESET}  {tmap}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
