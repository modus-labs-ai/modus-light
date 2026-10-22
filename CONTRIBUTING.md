# Contributing to Modus Light

Thanks for being here. Modus Light is a security runtime, so the bar for a change is
"provably correct", not "looks right" — and this document exists to make clearing that
bar straightforward rather than mysterious.

Participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md); conduct
concerns go to modus.labs.znz@gmail.com, and security vulnerabilities go through
private reporting as described in [SECURITY.md](SECURITY.md), never a public issue.

## The one-minute version

```bash
git clone https://github.com/modus-labs-ai/modus-light.git
cd modus-light
python -m pip install -e ".[dev]"
make verify
```

The `[dev]` extra matters: it pulls in `flake8`, and without it `make verify` stops at
the first gate with `No module named flake8`. The runtime itself has zero
dependencies — the extra is tooling only.

`make verify` is the gate. It runs the linter, the unit suite, the capability
benchmark, the compliance audit and every example script. Get it green locally before
you open a pull request; CI runs the same commands plus the two extra checks below.

## Requirements

- **Python 3.10 or newer.** `pyproject.toml` sets `requires-python = ">=3.10"`.
- **No runtime dependencies, and that is a feature.** Modus Light is designed to run
  in an air-gapped enclave, so `dependencies = []` in `pyproject.toml` is load-bearing.
  A pull request that adds a runtime dependency needs to argue why the capability
  cannot be built on the standard library. Additions to the `[dev]` extra
  (`pytest`, `flake8`) are an easier sell.
- **`setuptools>=77`** if you are building a wheel — earlier versions do not
  understand the PEP 639 SPDX `license = "BUSL-1.1"` expression.

## What `make verify` actually checks

| Target | Command | What it proves |
|---|---|---|
| `make lint` | `flake8 src tests examples` | style and dead code; 120-column limit, configured in `setup.cfg` |
| `make test` | `unittest discover -s tests` | the unit suite |
| `make benchmark` | `modus-light benchmark` | the 10 capability vectors execute and self-check |
| `make audit` | `modus-light audit` | the 15 compliance smoke checks pass |
| `make examples` | runs all `examples/*.py` | every shipped example still works end to end |

Before opening a pull request, also run the two things CI runs that `make verify`
does not:

```bash
python -O -m modus_light.cli audit        # with asserts stripped
for f in examples/*.py; do python -O "$f"; done
```

**Why `-O` matters, and it is not a formality.** `python -O` removes `assert`
statements *entirely*. If you write `assert do_the_work()`, the call vanishes in
optimized mode and the following success message still prints — a silently skipped
operation that reports success. Never put a side effect inside an `assert`. Use:

```python
done = do_the_work()
if not done:
    raise SystemExit("explain what was refused and why")
```

A bare `assert x is not None` is fine; stripping a pure check is harmless.

## Standards for a change

**Every behaviour change ships with a test.** Preferably one that fails before your
fix and passes after. Name it after the property it protects, not the function it
calls — `test_complete_rejects_a_foreign_worker` tells a reader what the system
guarantees; `test_complete_2` does not.

**Security changes must fail closed.** If authorization, a capability lease, a spend
ceiling or an input filter cannot reach a confident "yes", the answer is "no". A
change that converts a refusal into a silent pass will not be merged.

**Do not change a docstring to match a bug.** If the code and the docstring disagree,
decide which one is right and say so in the pull request. Both answers are legitimate —
`unshield()`'s docstring was corrected because the normalization behaviour was
deliberate — but the two must not be left contradicting each other.

**Documentation is executable here.** `tests/test_docs.py` extracts every
self-contained ```python block from `README.md`, `SECURITY.md` and `docs/*.md` and
runs it. A code sample that raises is a failing test, so update the docs in the same
commit as the code.

**Comments explain *why*.** The repository deliberately carries comments on
non-obvious decisions — why the ReBAC check snapshots under a lock, why the tuple
space bounds completed retention. Match that density. Do not narrate what the next
line plainly does.

**`typing` annotations are expected** on new public functions, and `Optional` returns
must be handled at the call site rather than dereferenced hopefully.

## Commit messages

Conventional commits, with the scope being the engine you touched:

```
fix(rebac): terminate cyclic member_of graphs with an iterative walk
feat(linda): bound completed-tuple retention
docs(security): correct the unshield round-trip claim
```

Explain the *why* in the body when the subject cannot carry it. If you fixed a bug,
state what the broken behaviour was, so the commit stands on its own in `git log`.

## Pull requests

1. Branch from `main`.
2. Keep it focused — one concern per pull request. A 40-file refactor bundled with a
   security fix means the security fix cannot be reviewed properly.
3. State in the description: what changed, why, how you verified it, and anything you
   deliberately did **not** do.
4. Confirm `make verify` is green and the two `-O` commands above pass.
5. If you changed a documented claim, number or behaviour, update `CHANGELOG.md` under
   `[Unreleased]`.

CI runs the suite on Python 3.10, 3.11, 3.12 and 3.13, builds a wheel, runs
`twine check`, then installs that wheel into a clean virtualenv and runs the demo from
it. Please do not be discouraged if the matrix catches something your local Python
did not — that is exactly its job.

## Reporting a security vulnerability

**Do not open a public issue, and do not put a proof of concept in one.** Use GitHub's
private vulnerability reporting on this repository (Security → Report a vulnerability).
Full policy, threat model and scope boundaries: [`SECURITY.md`](SECURITY.md).

## Licensing

Modus Light is licensed under the **Business Source License 1.1**, converting to
Apache 2.0 on **2029-10-18**. See [`LICENSE`](LICENSE) for the binding terms,
including the production-use limitation and the revenue threshold.

By opening a pull request you agree your contribution is licensed under those same
terms. If you are contributing on behalf of an employer, make sure you have the
authority to do so.

## Questions

Open a [GitHub issue](https://github.com/modus-labs-ai/modus-light/issues). A question
that turns out to be a documentation gap is a useful bug report, so ask it.
