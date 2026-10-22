<div align="center">

<img src="assets/hero_showcase.jpeg" alt="Modus Zen OS — The Sovereign Enterprise OS" width="420" />

# 🛡️ MODUS LIGHT
### The Sovereign Enterprise Agent Runtime (Community Edition)

[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Wire Overhead](https://img.shields.io/badge/Wire%20Overhead-0%20TOKENS%20(Tuple%20Space)-cyan.svg?style=for-the-badge&logo=sqlite&logoColor=white)](#-what-modus-light-does--how-it-works)
[![Security Policy](https://img.shields.io/badge/Security-Policy-blueviolet.svg?style=for-the-badge&logo=security&logoColor=white)](SECURITY.md)
[![License: BSL 1.1](https://img.shields.io/badge/License-BSL%201.1-rose.svg?style=for-the-badge)](LICENSE)

<br/>

**Modus Light** is a high-performance, zero-token sovereign autonomous agent runtime engineered to replace fragile, chatty conversational script chains with deterministic, self-healing enterprise runtime infrastructure.

[System Architecture](docs/ARCHITECTURE.md) • [Problems Solved](docs/PROBLEMS_AND_SOLUTIONS.md) • [Competitive Analysis](docs/COMPETITIVE_ANALYSIS.md) • [Security Policy](SECURITY.md) • [Code of Conduct](CODE_OF_CONDUCT.md) • [Enterprise vs Community](docs/LIGHT_VS_ENTERPRISE.md) • [Quickstart](#-quickstart) • [Customer Test Drive](#-interactive-customer-test-drive) • [Architect Portfolio](#-engineering-portfolio--custom-development)

</div>

<hr/>

## 🏛️ Executive Summary

Modern AI agent deployments fail in enterprise production because they are built on the wrong abstraction: **unstructured conversational message-passing**. 

Passing entire chat histories between agents results in quadratic ($O(N^2)$) token cost explosion, unconstrained API billing loops, ambient root execution vulnerabilities (OWASP ASI03 Confused Deputy), and total process failure whenever a Python script crashes.

**Modus Light is the missing Operating System Kernel for agentic AI.** 

It decouples untrusted LLM reasoning from deterministic state coordination, providing mathematically bounded spend gates, relationship-based capability leases, in-process fault isolation, and zero-wire-token task coordination—packaged into an ultra-clean Python 3.10+ package with **zero external runtime dependencies**.

---

## 📏 Scope: What This Is — and What It Is Not

Read this before you evaluate the code. It is the difference between a working
runtime and a slide deck.

| | **Modus Light (this repository)** | **Modus Zen OS (enterprise appliance)** |
|:---|:---|:---|
| **State** | In-memory, single process. A restart loses everything. | Durable WAL on RAID 10 NVMe |
| **Coordination** | Threads in one Python process. No IPC, no network bus. | Distributed DBOS transactional mesh |
| **Supervision** | OTP *pattern* implemented in Python — restart policies, restart-intensity windows, circuit breaking. It does not link BEAM/Erlang. | Production OTP mesh engine |
| **LLM dispatch** | None. Modus Light never calls a model provider; it is the *gate* you put in front of one. | Full dispatch mesh |
| **Policy administration** | Code-level `add_relation()` calls. No admin UI, no persistence. | Distributed ReBAC + FTS5 |
| **Verification** | 134 unit tests, 16 executable audit checks, 10 executable capability vectors. The CI workflow runs all of them across Python 3.10–3.13; that matrix was last verified by running it in containers for each version, because GitHub Actions is disabled on this account (see [CI status](#ci-status)). | 68-vector red-team suite and SOC 2 / HIPAA / FIPS posture are Enterprise scope, not part of this repository |

**What you can do with it today:** embed the five engines (TokenShield,
FinOps gate, ReBAC + capability leases, Linda tuple space, OTP-pattern
supervisor) in your own agent runtime; run them on one node; get a hard
pre-dispatch spend ceiling, a relationship-based authorization gate, signed
capability leases, and OTP one-for-one process isolation — a crashing actor
is contained to itself — with a circuit breaker, and with zero
dependencies and zero network egress.

**What you cannot do with it today:** run it as a multi-node cluster, persist
state across restarts, coordinate agents across processes, or point it at a
model provider and let it drive a conversation. Those are the enterprise
appliance's job.

> **Every number in this README is measured by the code in this repository.**
> `modus-light audit` executes 16 real checks and reports failures by name.
> `modus-light benchmark` executes 10 real assertions. Neither can report a
> green result it did not earn.

---

## 🚨 The 5 Production Failures Solved by Modus Light

> 📖 *For a deep mathematical and architectural breakdown, read the complete whitepaper: [docs/PROBLEMS_AND_SOLUTIONS.md](docs/PROBLEMS_AND_SOLUTIONS.md)*

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          5 PRODUCTION FAILURE MODES                             │
├───────────────────────┬──────────────────────────┬──────────────────────────────┤
│ Production Failure    │ Naive Industry Pattern   │ Modus Light Engine Solution  │
├───────────────────────┼──────────────────────────┼──────────────────────────────┤
│ 1. Token Explosion    │ Chatty $O(N^2)$ Logs     │ Linda Tuple Space (0 Tokens) │
│ 2. Runaway Spend      │ Post-Hoc Billing Alerts  │ Pre-Dispatch Step 5 Switch   │
│ 3. Privilege Abuse    │ Ambient Root API Keys    │ Google Zanzibar ReBAC (L0-L4)│
│ 4. Prompt Infiltration│ Raw String Forwarding    │ TokenShield NFKC/Bidi Gate   │
│ 5. Process Panics     │ Uncaught Python Crashes  │ OTP-Pattern Supervisor Trees  │
└───────────────────────┴──────────────────────────┴──────────────────────────────┘
```

1. **Quadratic Token Death Spirals ($O(N^2)$)**:
   * *Problem*: In conventional group-chat frameworks (AutoGen, CrewAI), every agent turn broadcasts full conversational histories to all other agents, causing prompt tokens to scale quadratically and crash context windows.
   * *Modus Light Solution*: **Decoupled Linda Tuple Space**. Agents coordinate via discrete task tuples (`out`, `in_lease`, `rd`, `complete`). The handoff reaches no model, so internal coordination consumes **0 external LLM wire tokens** — and because a hop is handed only the outputs it declared a dependency on, total prompt volume becomes linear in hop count instead of quadratic. **Measured, with `modus-light tokens`:**

     The workload is the five-stage pipeline in `token_meter.py`, repeated to
     reach each hop count, where every stage declares a dependency on at most
     two earlier outputs. That bounded fan-in is the condition the figures rest
     on, and it is stated here because it is the assumption that would quietly
     carry the claim if it went unmentioned.

     | Hops | Conversational replay | Tuple-space handoff | Reduction |
     |---:|---:|---:|---:|
     | 5 | 860 | 734 | **14.7%** |
     | 10 | 3,240 | 1,471 | **54.6%** |
     | 20 | 12,583 | 2,945 | **76.6%** |
     | 50 | 77,272 | 7,367 | **90.5%** |
     | 100 | 307,597 | 14,747 | **95.2%** |

     Read that honestly, because it is the most over-claimed number in this
     industry and we would rather you trusted the small figure than doubted the
     large one. **A short pipeline saves little** — at five hops it is 15%, not
     95% — because there is barely any redundant history to avoid re-sending.
     The saving grows because the right-hand column is flat at ~147 tokens per
     hop however long the pipeline gets, while the left-hand column re-sends
     everything said so far on every hop. Two further caveats we hold
     ourselves to: the baseline is the *naive* replay pattern, so a framework
     that summarises history lands between the two columns; and a pipeline
     whose every hop genuinely needs every prior output cannot save anything at
     all — a case the test suite asserts reports **zero**, not a flattering
     number. This runtime removes re-sent context, nothing more.

     Nothing above is a stored constant. `modus-light tokens` builds the actual
     prompt strings both architectures would send and counts them under three
     independent counting methods; past 20 hops the three agree to within 0.1
     of a percentage point, which is why the ratio does not depend on a
     tokenizer we cannot ship.

     **What this edition does and does not optimize.** Everything above comes
     from one mechanism: context that is never re-sent. That is the whole of
     the Community Edition's token strategy, and the table is its honest
     ceiling. Further token optimization — semantic deduplication across runs,
     cross-agent context compression and KV-cache-aware scheduling — belongs to
     **Modus Zen OS Enterprise**, which is a separate commercial product and
     not the code in this repository.

     *On the roadmap, not shipped:* a **Google Harness2** integration is
     planned for an upcoming Enterprise release, to bring agent evaluation and
     runtime policy under one set of unified controls. It is named here so the
     direction is public, and it is deliberately absent from every measured
     figure above — nothing in this repository depends on it.
2. **Catastrophic Runaway Cost Loops**:
   * *Problem*: Hallucinating agents trapped in tool-retry loops burn thousands of dollars in minutes; cloud billing alerts are post-hoc and arrive hours after the balance sheet has taken damage.
   * *Modus Light Solution*: **Step 5 Pre-Dispatch Spend Kill Switch**. An atomic in-memory spend governor evaluates token requirements *before* model sockets open, refusing a step whose estimate would breach the ceiling — so a halted loop spends nothing. The bound is on the *estimate*: a step that costs more than it predicted is reported as `overdraft_tokens` in the FinOps summary rather than assumed away.
3. **Ambient Root Authority & Confused Deputy Exploits (OWASP ASI03)**:
   * *Problem*: Tools execute with ambient administrative credentials; an indirect prompt injection co-opts the agent into executing privileged actions on behalf of unauthorized callers.
   * *Modus Light Solution*: **Google Zanzibar ReBAC Engine**. Monotonic 5-level capability attenuation ($L_0 \to L_4$) and cryptographically signed HMAC leases ensure child agents can never exceed parent authority. Leases can be **redeemed single-use**, so a captured lease cannot be replayed even while its signature is still valid.
4. **Adversarial Unicode & Trojan Source Bidi Infiltration (CVE-2021-42574)**:
   * *Problem*: Attackers evade security filters using Unicode zero-width characters, Cyrillic/Greek homoglyphs, and Right-to-Left (RTL) Bidi directional overrides.
   * *Modus Light Solution*: **TokenShield Lite**. A pure-CPU pipeline costing **$O(1)$ wire tokens — zero, with no model call at any input size** — and $O(n)$ CPU, linear in input length — combining NFKC canonical decomposition, zero-width stripping, homoglyph folding, and typed entity token masking (`<TOKEN_IP_X>`, `<TOKEN_EMAIL_X>`).
5. **Brittle Single-Threaded Process Crashes**:
   * *Problem*: An unhandled exception or API timeout in one agent terminates the entire Python process, wiping all in-flight state.
   * *Modus Light Solution*: **OTP-Pattern Supervisor Trees** (Python implementation of the Erlang OTP supervision pattern). One-For-One isolation catches worker panics, restarts the actor in place inside a restart-intensity window, and trips a circuit breaker during fatal loops.

---

## ⚙️ What Modus Light Does & How It Works

Modus Light operates as an in-process kernel pipeline between untrusted input and tool execution:

```
                                [ Untrusted Input ]
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 1. TOKENSHIELD LITE (0 Wire Tokens)                                             │
│    Unicode NFKC · Homoglyph Folding · Trojan Bidi Neutralizer · Entity Masking  │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 2. PRE-DISPATCH FINOPS GATEWAY ($0.00 Overdraft)                                │
│    Step 5 Spend Kill Switch · Atomic Spend Tracker · QoS Model Arbitrage        │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 3. GOOGLE ZANZIBAR ReBAC (Exact Tuples)                                         │
│    Tuple Store · Monotonic Attenuation (L0-L4) · HMAC Capability Leases         │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 4. LINDA TUPLE SPACE (Decoupled Coordination)                                   │
│    Asynchronous Tuple Dispatch (out, in_lease, rd) · Priority Queue · 0 Tokens  │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 5. OTP-PATTERN ACTOR SUPERVISOR (Self-Healing, Python)                          │
│    One-For-One Isolation · Automatic Standby Restarts · Circuit Breaker        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### The 5 Core Engines in Code:
```python
from modus_light import ModusLight, AttenuationLevel, ActorSpec

# Initialize sovereign runtime with a strict token budget ceiling
rt = ModusLight(tenant_id="fintech_enclave", spend_cap_tokens=5000)

# 1. Zero-Cost TokenShield: Sanitize untrusted input without wasting LLM tokens
shielded_prompt, token_map = rt.shield_prompt("Send payroll to cfo@example.com at 192.0.2.10")
# Returns: "Send payroll to <TOKEN_EMAIL_0> at <TOKEN_IP_1>"

# 2. Zanzibar ReBAC & Step 5 FinOps: Enforce relationship access & spend ceiling
reservation = rt.authorize_step(role="admin", sector="finance", estimated_tokens=150, prompt_tokens=120)
# Declare the prompt and reservation.max_tokens comes back as the generation
# budget that remains. Hand that to your provider as its output limit: providers
# bill input and output, so a limit set to the whole reservation would let the
# step cost prompt + reservation and breach its ceiling on every call.
print(reservation.max_tokens)        # generation budget, prompt already deducted
rt.commit_spend(actual_tokens=150, reservation=reservation)              # settles that reservation

# 3. Cryptographic HMAC Capability Lease: Bound subagent authority.
#    A lease is only ever issued over an existing relationship — the engine fails
#    closed, so grant the relation first rather than minting authority out of thin air.
rt.rebac.add_relation("worker_agent", "can_execute", "finance")

lease = rt.issue_capability_lease(
    subject="worker_agent",
    relation="can_execute",
    object_resource="finance",
    level=AttenuationLevel.L2_STANDARD_OPERATOR,
    duration_seconds=300
)

# Redeem it for a one-time action. Signature checking alone defeats forgery but
# not replay: a captured lease stays valid for its whole TTL. Redemption spends it.
# Not `assert`: `python -O` strips assert statements, and a check that vanishes
# under optimization is the one bug this runtime refuses to ship.
if not rt.redeem_capability_lease(lease):
    raise SystemExit("a valid lease should redeem once")
if rt.redeem_capability_lease(lease):
    raise SystemExit("a redeemed lease must never be accepted twice")

# 4. Decoupled Linda Space: Emit discrete task tuple (0 wire tokens exchanged)
task = rt.submit_task(topic="process_payroll", payload={"data": shielded_prompt}, priority=10)

# 5. OTP-pattern Actor Supervision: Execute under a panic-isolated supervisor
def safe_worker(task_id):
    return f"Processed task {task_id}"

rt.supervisor.register_actor(ActorSpec(name="payroll_worker", role="processor"), safe_worker)
result = rt.supervisor.execute_actor("payroll_worker", task_id=task.id)
```

---

## ⚡ Quickstart

### 1. Installation
Modus Light has **zero required external runtime dependencies** (pure Python 3.10+ standard library):

```bash
git clone https://github.com/modus-labs-ai/modus-light.git
cd modus-light
pip install -e .
```

### 2. Run the Examples Immediately
All examples include self-contained path bootstrapping and run directly from the repository root:

```bash
python3 examples/01_quickstart.py
python3 examples/02_finops_killswitch.py
python3 examples/03_zanzibar_rebac.py
python3 examples/04_actor_supervision.py
python3 examples/05_customer_test_drive.py
```

---

## 🎮 Interactive Customer Test Drive

Experience every core engine in under 60 seconds with **zero cloud setup**:

```bash
modus-light demo
```

```
================================================================================
  🛡️  MODUS LIGHT — SOVEREIGN ENTERPRISE AGENT RUNTIME
  Community Edition (BSL 1.1) • Zero-Token State • Google Zanzibar ReBAC
================================================================================
Welcome to the Modus Light Free Customer Test Drive!
Running completely in-process with 0 external cloud dependencies.
[Step 1/6] TokenShield Zero-Cost Entity Sanitization
  Input Prompt:  Contact admin@example.com at 192.0.2.10 with secret sk-ant-live-4938201948201948
  Masked Prompt: Contact <TOKEN_EMAIL_1> at <TOKEN_IP_2> with secret <TOKEN_SECRET_0>
  ✓ PII sanitized locally. 0 LLM wire tokens consumed.
[Step 2/6] Google Zanzibar ReBAC & Confused Deputy Defense
  Testing role: 'guest_attacker_admin' attempting 'cyber_defense' sector...
  ✓ Refused: Zanzibar ReBAC Refusal: Subject 'guest_attacker_admin' is not authorized to 'can_execute' on 'cyber_defense'.
  ✓ OWASP ASI03 Confused Deputy attack blocked at the authorization gate.
[Step 3/6] Pre-Dispatch Step 5 FinOps Spend Kill Switch
  Remaining budget: 1,000 tokens. Attempting rogue loop requesting 2,500 tokens...
  ✓ Refused: Step 5 FinOps Kill Switch Tripped: Adding 2500 tokens exceeds spend cap of 1000 (Current: 0). Refused before dispatch; this step spends nothing.
  ✓ Runaway loop halted before API dispatch (measured overdraft: $0.00).
[Step 4/6] Decoupled Linda Tuple Space (Zero-Token Coordination)
  Task Emitted: ID=1001, Topic='reconcile_gl_accounts', Priority=10
  ✓ Task Leased: Worker='worker_node_1', Status='LEASED'
  ✓ Task Completed over the in-process bus. 0 wire tokens exchanged.
[Step 5/6] OTP Supervisor Actor Recovery & Circuit Breaker
  Executing actor 'db_agent' under supervisor tree...
  ✓ Restarted in place and returned: recovered
  ✓ Panic Isolated: Supervisor Circuit Breaker Tripped: Actor 'ledger_agent' crashed 2 times in 10.0s (Max: 2). Root panic: Permanent Storage Fault
  ✓ Supervisor contained the crash loop and tripped the circuit breaker.
[Step 6/6] Runtime Telemetry & Enterprise Upgrade Readiness
  Status:             DEGRADED
  Edition:            Modus Light (Community Edition)
  Coordination Bus:   IN_PROCESS (no network transport)
  Wire Tokens Used:   0
  Air-Gap Verified:   True (no network imports in package)
  Actor Health:       {'db_agent': 'RUNNING', 'ledger_agent': 'TRIPPED'}
🎉 Test Drive Completed Successfully!
```

Step 6 reports `DEGRADED` on purpose: the demo deliberately trips a circuit
breaker in step 5, and the health endpoint reports the real actor state
instead of a hard-coded `HEALTHY`.

---

## ⚔️ Head-to-Head Competitive Analysis

> 📖 *For detailed technical teardowns, read the full report: [docs/COMPETITIVE_ANALYSIS.md](docs/COMPETITIVE_ANALYSIS.md)*

Run the empirical benchmark suite yourself:
```bash
modus-light benchmark
```

```
================================================================================
  ⚔️  MODUS LIGHT — CAPABILITY BENCHMARK RUNNER
  [PASS] W7.1 Zero-wire tuple coordination: 1 tuple routed in-process, 0 network calls
  [PASS] W7.2 Linda priority + FIFO routing: highest priority served first, FIFO within a priority
  [PASS] W7.3 ReBAC fail-closed kernel gate: unauthorized subject refused (fail-closed)
  [PASS] W7.4 Supervisor panic isolation + restart: crash isolated, restarted after 2 attempts
  [PASS] W7.5 Ephemeral staging latency: dispatch 0.0032 ms median / 0.0066 ms p95 under a 2,000-tuple backlog; stage+claim+complete round trip 0.0773 ms median (all measured, in-process)
  [PASS] W7.6 FinOps Step 5 spend kill switch: over-cap dispatch refused before any provider call
  [PASS] W7.7 HMAC capability lease custody: HMAC-SHA256 lease verified, tampering detected
  [PASS] W7.8 Unicode prompt-injection pre-filter: zero-width and bidi controls neutralized
  [PASS] W7.9 Homoglyph evasion neutralization: Cyrillic/Greek homoglyphs folded to ASCII
  [PASS] W7.10 Air-gap & symlink hygiene: 0 network transports imported, 0 symlinks
--------------------------------------------------------------------------------
  🎉 10/10 CAPABILITY VECTORS PASSED (0.0585s)
================================================================================
```

Every vector is an executable assertion against this runtime, and the runner
exits non-zero if any of them fails. Latency figures are measured locally on
the machine that ran the benchmark — they are not a claim about anyone else's
framework.

### Architectural Comparison Highlights

> **On the third-party figures below:** latency and token-overhead numbers
> attributed to other frameworks are **not** measured by this project — they
> are widely reported community/benchmarks figures and are reproduced here as
> context, not as verified measurements. Everything in the **Modus Light**
> column is measured by the code in this repository.

#### 1. Nous Hermes (Nous Research) vs. Modus Light
* **What Nous Hermes Is**: State-of-the-art open-weights model fine-tuned for structured tool calling and agentic reasoning.
* **The Synergy**: Hermes provides neural weights, but has no operating system kernel. It lacks memory isolation, pre-dispatch spend kill switches, ReBAC capability leases, and process fault tolerance.
* **The Sovereign Stack**: Pairing **Nous Hermes 3** (local inference) with **Modus Light** creates a 100% sovereign, air-gapped agent environment with zero external cloud egress and mathematical security boundaries.

#### 2. OpenClaw / OpenHands / Devin vs. Modus Light
* **The Heavyweight Container Bottleneck**: OpenClaw and OpenHands spin up dedicated Docker containers per agent, incurring a **15–45 second spin-up latency**, heavy memory consumption, and ambient root access inside containers.
* **The Modus Light Advantage**: in-process staging, granular Zanzibar capability leasing, and Linda tuple isolation that keeps conversational transcript bloat out of long programming sessions. Measured on the maintainer's workstation with `modus-light benchmark` — reproduce it on yours, the numbers come from the same code you just installed:

| Resident tuples | `submit_task` dispatch (median) | Full stage→claim→complete round trip (median / p95) |
|---|---|---|
| 0 | 0.002–0.004 ms | 0.04 ms / 0.19 ms |
| 2,000 | 0.002–0.004 ms | 0.70 ms / 1.23 ms |
| 5,000 | 0.002–0.004 ms | 1.98 ms / 3.33 ms |
| 20,000 | 0.002–0.004 ms | 8.20 ms / 14.13 ms |

  Dispatch is given as a range because that is what repeated runs produce: over eight runs the median stayed inside 0.0021–0.0039 ms and the p95 inside 0.0040–0.0064 ms, so anything quoted to a tighter precision than that would be noise dressed as a measurement.

  Read that honestly, because the two columns behave differently. **Dispatch is flat — $O(1)$ in queue depth**: it does not move between an empty space and 20,000 resident tuples, and the benchmark fails the build if the median drifts above the 0.05 ms regression gate — a deliberately loose gate, roughly 15x the observed median, so it catches an algorithmic regression without flaking on a slower or busier machine. **The round trip is $O(n)$ in backlog depth**, because claiming scans the resident set for the highest-priority matching tuple; it is sub-millisecond up to roughly 2,500 tuples and degrades linearly past that at about 0.4 µs per resident tuple. A queue that deep means workers are not keeping up, which is a capacity signal rather than a latency one — but it is not "sub-millisecond under load" and we will not call it that. Against a 15,000 ms Docker spin-up, dispatch is **over a million times faster**, and the full round trip is **over 3,000x faster at any backlog up to 5,000 tuples** (15,000 / 1.98) — still over 1,800x at 20,000.

#### 3. LangGraph & AutoGen vs. Modus Light
* **LangGraph**: StateGraph dictionary accumulation still causes $O(N)$ token inflation across turns; lacks pre-dispatch spend kill switches and OTP supervisor trees.
* **AutoGen / CrewAI**: Conversational group chats suffer from severe $O(N^2)$ message broadcast overhead and ambient shared credentials. Modus Light replaces chatty threads with zero-token typed tuple coordinates.

| Feature & Dimension | **Modus Light** | **Nous Hermes** | **OpenHands / OpenClaw** | **LangGraph** | **AutoGen / CrewAI** | **Temporal** |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Core Abstraction** | **Sovereign Actor DAG** | Fine-Tuned Weights | Docker Coding Agent | Cyclic StateGraph | Conversational Chat | Durable Workflow |
| **Inter-Agent Wire Tokens** | **0 Wire Tokens** | $O(N)$ Token Inflation | High (Shell Logs) | $O(N)$ State Accumulation | $O(N^2)$ Chat Broadcast | N/A (Token-Blind) |
| **Task Dispatch Latency** | **0.002–0.004 ms median, under 0.01 ms p95 (measured, in-process, $O(1)$ in queue depth — see the latency table above for the full round trip, which is $O(n)$)** | Network Inference Bound| 15,000–45,000 ms (Docker) | 1.5–5.0 ms | 10–50 ms | 5–25 ms |
| **External Dependencies** | **0 (Pure Python Stdlib)**| Model Weights (GGUF) | Docker, Python, Node | LangChain Ecosystem | Many PyPI Packages | Server, DB, Worker |
| **Pre-Dispatch FinOps Gate** | **Step 5 Kill Switch ($0.00)** | None | None | None | None | Queue Limit Only |
| **Access Control Engine** | **Google Zanzibar ReBAC** | None | Ambient Root in Docker | None (Ambient Keys) | None (Shared Tools) | Generic RBAC |
| **Capability Attenuation** | **5-Level Monotonic (L0–L4)** | None | None | None | None | Static Roles |
| **Fault Recovery Model** | **OTP-Pattern Supervisor (Python)** | None | Container Restart | Python Exception Panic | Unhandled Process Abort| Event Replay |
| **Adversarial Input Defense** | **NFKC + Homoglyph + Bidi** | Model-Level Safety | None | None | None | None |

---

## 💼 Modus Zen OS Enterprise: Sovereign Hardware Appliance

Modus Light is the developer and community runtime. For mission-critical banking, defense, healthcare, and sovereign infrastructure, **Modus Zen OS Enterprise** is delivered as a turnkey, air-gapped bare-metal hardware appliance.

**What follows describes a separate commercial product, not the code in this repository.** Read it as a specification confirmed in writing during procurement rather than as something this repo demonstrates — everything above this line is measured by a command you can run, and nothing below it is. Compliance regimes are named as design targets; **Modus Light itself carries no certification or attestation.**


| Architecture Dimension | **Modus Light (Community)** | **Modus Zen OS (Enterprise Sovereign Appliance)** |
|:-----------------------|:---------------------------:|:-------------------------------------------------:|
| **Commercial License** | Business Source License 1.1 (BSL) | Enterprise Commercial License (terms on request) |
| **Deployment Target** | Single Node / Developer Laptop | Turnkey Bare-Metal Air-Gapped Appliance |
| **Compute Architecture** | Standard CPU / Single GPU | Dual AMD EPYC 9654 / Intel Xeon Platinum (64–128 Cores) |
| **NUMA Isolation** | Single Memory Domain | Dual NUMA Enclave (Node 0 OS/RAM-Disk; Node 1 Neural Mesh) |
| **Neural Inference Mesh** | Local LLM / Cloud API Proxy | 4x–8x NVIDIA H100 80GB (320–640GB VRAM, NVLink) or 8x L40S 48GB (384GB, PCIe — no NVLink); mesh sized to the model during scoping |
| **Storage Subsystem** | In-Memory / SQLite State | Hardware RAID 10 NVMe (up to 28,000 MB/s read; writes roughly half, since RAID 10 mirrors every block). WAL commit latency is benchmarked on the delivered appliance |
| **Ephemeral Tool Staging** | Clean Python Interfaces | 22-Sector Ephemeral WASI RAM-Disk; staging latency quoted per sector during scoping |
| **Command & Control (C2)** | In-Process HMAC Leasing | Signal / WhatsApp / Telegram 2-Person Cryptographic Quorum |
| **Predictive Analytics** | Heuristic Arbitrage | TimesFM 3-Tier Probabilistic Quantile Forecasting |
| **Adversarial Red-Teaming**| 10 Public Benchmark Vectors | 68 Battle-Tested Vectors (OWASP ASI01–ASI10) |
| **Compliance Readiness** | Developer evaluation. **Modus Light itself carries no certification or attestation.** | Engineered for deployments that must satisfy SOC 2 Type II, HIPAA, FIPS 140-3 and GDPR Chapter V. Certification status, including whether a FIPS 140-3 CMVP certificate applies to a given configuration, is confirmed in writing during procurement — not by this table |
| **Support & SLAs** | Community / GitHub Issues | 99.999% HA Uptime · 15-Minute P1 SLA · Dedicated Field Eng |

### The 30-Day Turnkey Enterprise Pilot (scope and terms on request)
Enterprises can test Modus Zen OS in their own private data centers. Scope, acceptance criteria and commercial terms are agreed in writing during procurement:
* **Week 1**: Ingress Gateway Drop-In & Baseline Spend Telemetry Audit.
* **Week 2**: TokenShield Entity Masking & Zanzibar ReBAC Schema Mapping.
* **Week 3**: 22-Sector JIT RAM-Disk Sandboxing & Out-of-Band Multi-Channel C2.
* **Week 4**: 68-Vector Adversarial Penetration Testing & Executive ROI Signoff.

---

## 👨‍💻 Engineering Portfolio & Custom Development

Modus Light and Modus Zen OS were engineered by a systems architect specializing in high-performance autonomous agent infrastructure, kernel-level sandboxing, and adversarial AI defense.

### Technical Capabilities Available for Engagement:
* **Custom Autonomous Agent Runtime Engineering**: Designing deterministic actor DAGs, event buses, and zero-token memory architectures for proprietary enterprise workflows.
* **Sovereign Air-Gapped AI Deployments**: Engineering bare-metal NUMA appliances, local vLLM/Ollama inference meshes, and air-gapped on-premise clusters.
* **AI FinOps & Pre-Dispatch Governance**: Implementing mathematical spend kill switches, dynamic model tier arbitrage, and multi-tenant quota systems.
* **Adversarial Red-Teaming & Security Audits**: Hardening agent deployments against OWASP Top 10 for Agentic AI (ASI01–ASI10), Trojan Source Bidi attacks, and Confused Deputy exploits.

To discuss custom enterprise development, architectural advisory, or sovereign AI appliance deployment:
* **Contact & Inquiries**: open a [GitHub issue](https://github.com/modus-labs-ai/modus-light/issues) — the fastest route, and it leaves a public record of the question.
* **Project Home**: [https://github.com/modus-labs-ai/modus-light](https://github.com/modus-labs-ai/modus-light)

---

## 🧪 Testing, Quality & Compliance

Modus Light is subject to strict automated verification. The runtime needs nothing
beyond the standard library, but the linter does — install the dev extra first, or
`make lint` stops with `No module named flake8`:

```bash
pip install -e ".[dev]"
```

```bash
# Run the unit suite across all 5 core engines
make test

# Run 10 executable capability benchmark vectors
make benchmark

# Run the 16-point compliance audit (every check is executed, failures listed by name)
make audit

# Run the linter (flake8, max-line-length 120)
make lint

# Run every gate above in one pass
make verify
```

### CI status

**Read this before you judge the Actions tab.** `.github/workflows/ci.yml` defines the
full gate — linter, unit suite, every CLI command, every example (twice, the second time
under `python -O`), a wheel build, `twine check`, and a clean-virtualenv install that
runs the demo from the built artifact rather than from the source tree — across Python
3.10, 3.11, 3.12 and 3.13, on every push to `main` and every pull request.

GitHub Actions is **disabled on the account that owns this repository for a billing
reason unrelated to the code**, so jobs are created and then never start. You will
therefore find no green checkmark here, and we would rather say so than let you discover
it and wonder what is being hidden.

Because a workflow nobody can run is not evidence, the matrix was executed locally
instead, in a clean container per interpreter:

| Interpreter | Result |
|---|---|
| Python 3.10 | 134 tests OK · all 5 CLI commands OK · all 5 examples OK, normally and under `-O` |
| Python 3.11 | 134 tests OK · all 5 CLI commands OK · all 5 examples OK, normally and under `-O` |
| Python 3.12 | 134 tests OK · all 5 CLI commands OK · all 5 examples OK, normally and under `-O` |
| Python 3.13 | 134 tests OK · all 5 CLI commands OK · all 5 examples OK, normally and under `-O` |

Reproduce any row in one command, substituting the version you care about:

```bash
docker run --rm -v "$PWD":/w -w /w python:3.12-slim \
  sh -c 'pip install -q ".[dev]" && python -m unittest discover tests'
```

That is the honest version of a badge: you do not have to trust the claim, because the
command that produces it is right here.

Every self-contained Python block in `README.md`, `SECURITY.md` and `docs/*.md` is
extracted and executed by `tests/test_docs.py`. A documented example that stops working
is a failing test.

---

## 🤝 Contributing & Release History

* **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — the contribution gate: `make verify`, the
  `python -O` checks, test and commit conventions, and the fail-closed rule for
  security changes.
* **[`CHANGELOG.md`](CHANGELOG.md)** — every notable change, following Keep a Changelog
  and Semantic Versioning.
* **[`SECURITY.md`](SECURITY.md)** — threat model and disclosure policy. Report
  vulnerabilities through GitHub's private vulnerability reporting, never a public
  issue.

---

## 📜 License & Open Source Evolution

Modus Light is published under the **Business Source License 1.1 (BSL 1.1)**:
* **Always free, for anyone**: non-production use — evaluation, development, testing, benchmarking, security research and academic research — is granted by the licence itself, with no revenue condition attached. Read, modify and redistribute it freely.
* **Free in production below USD $100,000 annual gross revenue**, provided you are not reselling Modus Light to third parties as a managed service, hosted platform or network-accessible API. The exact wording is the Additional Use Grant in [`LICENSE`](LICENSE), which is the canonical BUSL-1.1 text with our parameters filled in — nothing bespoke for your counsel to untangle.
* **Automatic open-source conversion**: becomes **Apache License 2.0** on `2029-10-18`, or four years after a version's first public release, whichever is sooner. That date is in the licence, so it is not ours to walk back.
* **Enterprise Commercial License**: production use above that revenue threshold, any managed-service or hosted offering, and the bare-metal appliance. Open a [licensing issue](https://github.com/modus-labs-ai/modus-light/issues) to start the conversation.

> BSL 1.1 is **not** an OSI-approved open-source licence, and we say so plainly rather than letting the badge imply otherwise. Each released version becomes Apache 2.0 on the schedule above.

---

<div align="center">
<sub>Engineered with mathematical precision. Zero external dependencies. Zero private leaks.</sub>
</div>
