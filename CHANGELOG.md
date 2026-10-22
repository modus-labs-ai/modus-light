# Changelog

All notable changes to Modus Light are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [1.0.0] — 2026-10-22

First public release of the Community Edition: a zero-dependency Python runtime that
places an operating-system kernel between untrusted LLM reasoning and tool execution.

### Added

- **TokenShield** — Unicode input firewall. NFKC normalization, zero-width stripping,
  Trojan Source Bidi neutralization (CVE-2021-42574), homoglyph folding, and typed
  entity masking for secrets, emails, IPs and payment cards. Card detection is
  Luhn-checked, so a 16-digit order number is not mistaken for a PAN. Masked entities
  round-trip exactly through `unshield()`; the normalization is deliberately not
  reversed, because that sanitisation *is* the security property.
- **FinOps Step 5 Gateway** — a pre-dispatch spend kill switch. A step's token cost is
  evaluated *before* any socket opens, so a refused runaway loop spends nothing
  rather than at the next billing alert.
  - **The reservation is a ceiling, not a prediction.** `reservation.max_tokens`
    returns the generation budget with the prompt already deducted — declare it with
    `authorize_step(..., prompt_tokens=N)` — and that is the number to hand a provider
    as its output limit. Providers bill input *and* output, so a limit set to the whole
    reservation would let a step cost prompt + reservation and breach on every call.
  - **Settling above the ceiling raises** `ReservationCeilingBreachedError` (a subclass
    of `SpendCapExceededError`, so existing handlers keep working) and increments
    `ceiling_breaches`. The spend is still recorded truthfully: the tokens are already
    gone, and the only question is whether the operator learns it now or from an
    invoice.
  - Consequently **spend cannot exceed reservations, and reservations cannot exceed the
    cap** — `$0.00` overdraft is arithmetic, not aspiration, for every step that
    settles through its reservation within its ceiling. Pinned over 200 randomised
    schedules in `tests/test_security_properties.py`. Anonymous commits and
    `enforce_reservation_ceiling=False` sit outside that guarantee, and for those the
    overrun is measured and reported rather than assumed away.
  - Token counts are validated as finite and non-negative before they reach the
    comparison, because a kill switch that `reserve(-10**9)` or `float("nan")` can
    disable is not a kill switch.
- **Google Zanzibar ReBAC** — subject-relation-object tuples with transitive
  `member_of` resolution, monotonic L0–L4 capability attenuation, and HMAC-SHA256
  capability leases bound to a subject's authority ceiling, keyed with a full 256-bit
  CSPRNG secret (`secrets.token_bytes(32)`).
  - **Leases can be redeemed single-use, so replay is refused rather than merely
    time-boxed.** A signature check proves a lease is authentic and unexpired, which
    defeats forgery but not replay: a captured lease is otherwise usable for the whole
    of its TTL. `redeem_capability_lease()` spends the lease, so the second
    presentation is refused — use it for anything that must happen once. Redeemed ids
    are forgotten at expiry, so the registry cannot grow without bound, and
    `verify_lease()` stays non-consuming for capabilities that are legitimately
    reusable within their lifetime. The registry is per-process, matching the rest of
    this runtime; cluster-wide single-use is an Enterprise concern.
  - Lease signatures cover a **length-prefixed** encoding of their fields, so no two
    different leases can produce the same signing input.
  - Authorization decisions are **cycle-safe**: group resolution is an iterative
    breadth-first walk with a `visited` set, so a `member_of` cycle
    (`team_a → team_b → team_a`) terminates with a decision instead of exhausting the
    stack.
  - Decisions are **safe under concurrent writers**: a read walks an immutable
    `frozenset` snapshot taken under the lock, so a relation written mid-decision
    cannot disturb an in-flight check.
  - Unknown subjects, unknown objects, missing relations and an unresolvable
    attenuation path all **fail closed**: `authorize()` raises
    `AuthorizationDeniedError` rather than returning a permissive default, and a
    lease is only ever issued over a relation that already exists.
- **Linda Tuple Space** — decoupled `out` / `rd` / `in_lease` / `complete`
  coordination with priority dispatch, replacing O(N²) conversational broadcast with
  discrete typed tuples and zero inter-agent wire tokens.
  - The lease is **enforced, not advisory**: `complete()` requires the tuple to be in
    `LEASED` state and takes `worker_id` as a required keyword argument that must match
    the lease holder — so one agent cannot close out another's work, and a duplicate
    result cannot overwrite the first. It returns `False` rather than raising, so a worker that lost a race can
    simply claim the next tuple.
  - Completed-tuple retention is **bounded** (`completed_retention`, default 1000,
    oldest-first eviction), so a long-running coordinator does not grow without limit.
  - **Stranded leases are reclaimed.** A worker that dies mid-task never calls
    `complete()`, which would otherwise leave the tuple `LEASED` forever and the work
    silently dropped — invisible, because the queue reports it as in progress rather
    than failed. Leases carry a `leased_at` stamp and return to `PENDING` after
    `lease_timeout_seconds` (default 300), the dead worker's stale handle is then
    refused, and `leases_reclaimed` counts it. Set the timeout to `None` for
    at-most-once delivery instead of at-least-once.
- **OTP-pattern Supervisor** — one-for-one process isolation with per-actor restart
  budgets, restart-intensity windows, `permanent` / `transient` / `temporary` policies,
  and a circuit breaker that trips on a crash loop. A tripped breaker is terminal by
  design and reopens only through an explicit `reset_actor()`, so a crash loop is never
  reclosed on a timer.
- **CLI** — `modus-light demo` (6-step interactive test drive), `benchmark` (10
  executable capability vectors, each self-checking and failing loudly), `audit` (16
  compliance checks, every one executed, failures listed by name), `tokens` (the
  measured token-reduction report described below), `info`, and `shield`. Also `--version`, and `python -m modus_light` for installs where the
  console script is not on `PATH` (`pip install --user`, or an unactivated venv).
- **Output that survives a stream that is not a UTF-8 terminal.** The status glyphs
  are non-ASCII, and `cp1252` — what Windows uses for a redirected stream — cannot
  encode them, so `modus-light audit > audit.log` would have raised
  `UnicodeEncodeError` *after* the audit passed, turning a clean run into a non-zero
  exit. Linux is normally spared by PEP 538/540 locale coercion, but an explicit
  `PYTHONIOENCODING=ascii` defeats that as well. Streams are now reconfigured with
  `errors="replace"`, so a glyph degrades to `?` rather than losing the exit status.
  Pinned by subprocess tests that run every command under an ASCII-only stream.
- **Colour only on a terminal.** ANSI codes are suppressed when stdout is a pipe or a
  file, when `TERM=dumb`, and when [`NO_COLOR`](https://no-color.org) is set — so a CI
  log or a `tee` captures greppable text instead of escape sequences.
- **Five runnable examples** in `examples/`, from quickstart to a full customer test
  drive. They are verified under `python -O` as well as normally, so no shipped example
  can hide a side effect inside an `assert` that optimized mode would strip.
- **Measured token reduction — `modus-light tokens`.** Every token figure this project
  publishes is produced by a command anyone can run. `modus_light.token_meter` executes
  the same pipeline under conversational replay and under tuple-space handoff, builds
  the prompt strings each architecture would actually send, and counts them:
  **14.7% at 5 hops, 54.6% at 10, 76.6% at 20, 90.5% at 50 and 95.2% at 100.**
  Read with the pipeline length attached, because a short pipeline saves little and the
  distinction is what matters when sizing a deployment. The mechanism is that the
  tuple-space column stays flat at ~147 tokens per hop while conversational replay grows
  quadratically; the handoff itself costs zero tokens because it reaches no model.
  Reported under three independent counting methods that agree to within 0.1 of a
  percentage point past 20 hops — the package has no dependencies and therefore no real
  tokenizer to call, so the ratio is the claim, and the ratio is tokenizer-independent.
  The meter can report **zero**, and the suite asserts that it does: a pipeline whose
  every hop genuinely needs every prior output saves nothing, because a measurement that
  cannot deliver bad news is not a measurement. The published table is regenerated and
  compared row by row, and every token-reduction percentage in the documentation is
  required to name the pipeline length it applies to.
- **Environment configuration** — `MODUS_TENANT_ID` and `MODUS_SPEND_CAP_TOKENS` are
  read from the environment, with explicit arguments taking precedence. A malformed
  spend cap raises `ConfigurationError` rather than silently falling back to a default
  ceiling: a kill switch must never guess its own limit.
- **134 unit tests** across the five engines, plus `tests/test_docs.py`, which extracts
  and executes every self-contained Python block in `README.md`, `SECURITY.md` and
  `docs/*.md` — so a documented example cannot silently rot. The published counts are
  pinned too: the test suite fails if the README advertises a number of tests, audit
  checks or benchmark vectors that differs from what actually executes.
- **Published claims are checked against the code, not against a reviewer's memory.**
  `tests/test_docs.py` fails if the README states a latency regression gate other than
  the one `cli.py` enforces, if the Python badge disagrees with `requires-python` and
  the classifiers, if the zero-dependency promise stops being literally true, or if any
  document describes the tuple-space round trip as sub-millisecond under load, which it
  is not: the round trip is $O(n)$ in backlog depth and the documentation says so.
  Performance figures are stated as measured ranges with their conditions, because a
  single number quoted to four decimal places implies a precision that repeated runs do
  not support.
- **CI** — GitHub Actions matrix across Python 3.10–3.13 running the linter, the unit
  suite, all CLI commands, every example (twice, once under `python -O`), a wheel
  build, `twine check`, and a clean-virtualenv install that runs the demo from the
  built artifact rather than from the source tree.
- **`SECURITY.md`** — threat model, security invariants, explicit out-of-scope
  boundaries, and private vulnerability reporting as the disclosure channel.
- **`CONTRIBUTING.md`** — the contribution gate, including the fail-closed rule for
  security changes and why a side effect must never live inside an `assert`.
- **`CODE_OF_CONDUCT.md`** — Contributor Covenant 2.1 with a named enforcement contact,
  because a code of conduct without an address to report to is decoration. It also
  routes security reports away from itself and into private vulnerability reporting: a
  conduct inbox is the wrong place to disclose a flaw to the whole world.
- **The Community Edition's token strategy is stated with its ceiling.** The saving comes
  from one mechanism — context that is never re-sent — and the measured table is as far
  as that mechanism goes. Further token optimization (semantic deduplication across
  runs, cross-agent context compression, KV-cache-aware scheduling) is **Modus Zen OS
  Enterprise** work and is not in this repository. A **Google Harness2** integration is
  published as roadmap for an upcoming Enterprise release, to bring agent evaluation and
  runtime policy under unified controls; it is labelled as planned rather than shipped,
  and no measured figure in this repository depends on it.
- **Licensing** — the canonical Business Source License 1.1 text with our parameters
  filled in, converting to **Apache License 2.0 on 2029-10-18** (or four years after a
  version's first public release, whichever is sooner). Non-production use —
  evaluation, development, testing, benchmarking, security and academic research — is
  granted by the licence itself with no revenue condition. Production use is granted
  below **USD $100,000** annual gross revenue, provided the use is not reselling the
  work to third parties as a managed service, hosted platform or network-accessible
  API. BSL 1.1 is not an OSI-approved open-source licence, and the README says so
  rather than letting the badge imply otherwise.

[Unreleased]: https://github.com/modus-labs-ai/modus-light/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/modus-labs-ai/modus-light/releases/tag/v1.0.0
