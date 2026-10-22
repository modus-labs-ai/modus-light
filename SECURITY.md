# 🛡️ Security Policy & Threat Model

Modus Light is engineered with security and determinism as primary architectural invariants. We take the security of our sovereign runtime, capability lease engine, and adversarial input shields seriously.

---

## 🔒 1. Supported Versions

Security updates, vulnerability patches, and CVE advisories are actively maintained for the following versions:

| Version | Supported | Security Maintenance Status |
|:---|:---:|:---|
| `1.0.x` (Current) | ✅ Yes | Active security patches and critical vulnerability advisories |
| `< 1.0.0` (Pre-release) | ❌ No | Unsupported; upgrade to the latest stable release |

---

## 🚨 2. Reporting a Vulnerability

We appreciate the efforts of security researchers and practitioners in identifying vulnerabilities. If you discover a potential security flaw in Modus Light, please report it responsibly:

### Preferred Method: GitHub Private Vulnerability Reporting
Please **do not open a public issue** for suspected vulnerabilities. Instead, submit a private advisory directly through GitHub:
👉 **[Report a Vulnerability on GitHub](https://github.com/modus-labs-ai/modus-light/security/advisories/new)**

### If You Cannot Use GitHub Advisories
We do not publish an email or PGP contact, so private vulnerability reporting above is
the only confidential channel — please use it if you possibly can. If you cannot:
* **Fallback:** open a regular issue at [https://github.com/modus-labs-ai/modus-light/issues](https://github.com/modus-labs-ai/modus-light/issues) that states a security
  problem exists and asks a maintainer to open a private advisory — **do not include the
  details, reproduction steps, or proof of concept in that public issue.**

### What to Include in Your Report
To accelerate triage and remediation, please provide:
1. **Description:** Clear summary of the vulnerability and its potential impact.
2. **Affected Component:** Core engine involved (`token_shield`, `finops`, `rebac`, `linda`, `supervisor`, `cli`, or `client`).
3. **Reproduction Steps:** Minimal, reproducible code sample or step-by-step instructions.
4. **Proof of Concept (PoC):** Demonstrating the security boundary bypass.
5. **Suggested Remediation:** Any proposed code fix or mitigation (if available).

### Response Timelines & SLAs
The engineering team adheres to the following coordinated disclosure SLAs:
* **Initial Acknowledgement:** Within **48 hours** of report receipt.
* **Triage & Severity Assessment:** Within **72 hours** with severity scoring (CVSS v3.1).
* **Remediation & Patch Delivery:**
  * **Critical / High Severity:** Fix released within **14 calendar days**.
  * **Medium / Low Severity:** Fix released within **30 calendar days**.
* **Public Coordinated Disclosure:** Coordinated release of security advisory and patch once users have had reasonable time to upgrade.

---

## 🏛️ 3. Threat Model & Security Invariants

Modus Light is designed to serve as an in-process operating system kernel that isolates untrusted AI reasoning from deterministic execution. The following guarantees represent non-negotiable security invariants:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      MODUS LIGHT THREAT DEFENSE INVARIANTS                      │
├──────────────────────────┬──────────────────────────────────────────────────────┤
│ Defense Dimension        │ Mathematical & Architectural Guarantee               │
├──────────────────────────┼──────────────────────────────────────────────────────┤
│ FinOps Pre-Dispatch Gate │ Pre-dispatch kill switch; a refused step spends none │
│ Google Zanzibar ReBAC    │ Monotonic attenuation ($L_0 \to L_4$), HMAC leasing  │
│ TokenShield Lite         │ Unicode NFKC, homoglyph folding, Trojan Bidi defense │
│ Erlang OTP Supervisor    │ One-for-one process isolation, circuit dampening     │
│ Linda Tuple Space        │ Single-owner task leasing, 0 inter-agent wire tokens │
└──────────────────────────┴──────────────────────────────────────────────────────┘
```

> **On "process isolation":** this is OTP's sense of the word — a *process* is a
> supervised actor, and a crashing actor is contained to itself without taking its
> siblings or the supervisor down. It is crash containment inside one OS process,
> not an OS-level or hardware sandbox: a supervised actor shares the interpreter,
> so it is not a boundary against memory disclosure or a determined escape.
> OS-process and enclave isolation are Enterprise concerns.

### 3.1 Pre-Dispatch FinOps Spend Governor
* **Guarantee:** Before any model socket opens or external tokens are committed, the runtime evaluates estimated consumption against the tenant budget ceiling.
* **Security Behavior:** If `current_spend + estimated_tokens > spend_cap_tokens`, execution is halted immediately with `SpendCapExceededError`, so a refused step spends nothing.
* **$0.00 overdraft, enforced in three places:** a refused step never dispatches, so it spends nothing. An admitted step is bound at the provider — `reservation.max_tokens` returns the generation budget with the prompt already deducted, so prompt plus output cannot exceed what the step reserved. And settling above that ceiling raises `SpendCapExceededError` and increments `ceiling_breaches`. Consequently, when every step settles through its reservation and within its ceiling, total spend cannot exceed the cap and `overdraft_amount` is `$0.00` — this is an arithmetic consequence of `reserve()` refusing anything above the remaining budget, not an aspiration. `tests/test_security_properties.py` pins it.
* **What is still measured rather than assumed:** a caller who bypasses the reservation (committing spend anonymously) or disables the ceiling with `enforce_reservation_ceiling=False` is outside that guarantee. For those paths the overrun is reported as `overdraft_tokens` / `overdraft_amount` rather than treated as impossible.

### 3.2 Google Zanzibar Relationship-Based Access Control (ReBAC)
* **Guarantee:** Tools and sector resources execute with zero ambient authority. Access requires valid subject-relation-object tuples.
* **Monotonic Attenuation ($L_0 \to L_4$):** Child subagents inherit an authority ceiling strictly bounded by their parent:
  $$\text{Level}_{\text{child}} \le \text{Level}_{\text{parent}}$$
  Subagents can never escalate privileges, mitigating **OWASP ASI03 Confused Deputy** vulnerabilities.
* **HMAC Cryptographic Leases:** Temporary leases are signed using HMAC-SHA256 over a length-prefixed encoding of their fields, with a millisecond TTL. Forging or editing a lease is infeasible without the signing key, and an expired lease is refused.
* **What a lease is not:** it is a bearer token. It is not single-use and cannot be revoked before expiry, so a leaked lease stays valid for the remainder of its TTL — this is not replay protection. Keep `duration_seconds` short, and treat a lease as a secret in transit.

### 3.3 TokenShield Adversarial Ingress Gate
* **Guarantee:** Ingested strings undergo a fixed-pass normalization costing **$O(1)$ wire tokens — zero, at any input size, because no model is called** and $O(n)$ CPU, linear in input length, before reaching tokenizers:
  * **Unicode NFKC Decomposition:** Eliminates ambiguous character representations.
  * **Zero-Width Stripping:** Removes hidden non-printable payload carriers (`\u200B`–`\u200D`, `\uFEFF`, `\u00AD`).
  * **Homoglyph Folding:** Transliterates lookalike Cyrillic and Greek characters to ASCII equivalents.
  * **Trojan Source Bidi Neutralization (CVE-2021-42574):** Strips directional override characters (`\u202A`–`\u202E`, `\u2066`–`\u2069`) preventing visual source code obfuscation.
  * **Entity Masking:** Replaces PII, secrets, and internal IPs with typed tokens without leaking sensitive data to external LLM APIs.

### 3.4 Erlang OTP Process Supervision
* **Guarantee:** Worker actor panics and unhandled exceptions are caught and contained within an isolated execution boundary (`ONE_FOR_ONE`). A crashing worker cannot corrupt sibling actor state or crash the host runtime.
* **Circuit Breaker Dampening:** Repeated actor crashes within a sliding time window trip `CircuitBreakerTrippedError`, preventing runaway crash loops and resource exhaustion.

---

## 🚫 4. Out-of-Scope Threat Boundaries

The following areas fall outside the security guarantees of the community Modus Light in-process runtime:

1. **Host Operating System / Root Compromise:**
   * If an attacker gains root or superuser execution privileges on the underlying host operating system, in-process Python memory boundaries cannot be guaranteed.
2. **Third-Party Model Provider Infrastructure:**
   * Telemetry, retention, or prompt logging policies enforced by external commercial model providers (when using external API keys rather than local air-gapped open weights like Nous Hermes).
3. **Malicious C-Extensions / Native Binaries:**
   * Modus Light is implemented strictly in pure Python standard library. Invoking unverified third-party C-extensions or compiled binaries outside Modus Light escapes Python interpreter protections.

> 💡 **Need Hardware-Enforced Air-Gap Enclaves?**  
> For organizations requiring bare-metal AMD SEV-SNP memory encryption, dual NUMA enclaves, and 22-sector ephemeral WASI RAM-disk sandboxing, see **[Modus Zen OS Enterprise](docs/LIGHT_VS_ENTERPRISE.md)**.

---

## 🛡️ 5. Security Best Practices for Implementers

When embedding Modus Light into production workflows:
1. **Never Run as Root:** Always execute agent workers under a dedicated, unprivileged system user (`UID 1000`).
2. **Enforce Token Spend Ceilings:** Always initialize `ModusLight(spend_cap_tokens=...)` with an explicit budget limit.
3. **Restrict Lease Ceilings:** Grant subagents the minimum required attenuation level (e.g., `L1_READ_ONLY` or `L2_STANDARD_OPERATOR`). Never issue `L4_SOVEREIGN_ENCLAVE` leases to untrusted pipelines.
4. **Scan Before You Push:** Run a secret scanner in CI — GitHub secret scanning and push protection, or a pre-commit hook such as `gitleaks`, `trufflehog`, or `detect-secrets` — so credentials and private network addresses never reach a remote.

---

## 📜 6. Safe Harbor Policy

We consider security research conducted in good faith to be an invaluable contribution to the community. Modus Light commits to:
* **No Legal Action:** We will not pursue legal action against researchers for accidental, good-faith violations of this policy.
* **Coordination & Credit:** We will coordinate with you on disclosure timelines and publicly acknowledge your contribution in our security advisories (unless you prefer anonymity).
* **Safe Testing Guidelines:**
  * Do not compromise real user data or corporate assets.
  * Do not execute denial-of-service (DoS) attacks against production infrastructure.
  * Give the maintainers reasonable time to address and patch reported vulnerabilities before public disclosure.

---

<div align="center">
<sub>Modus Light Security Policy • Maintained by the Modus Architecture Team</sub>
</div>
