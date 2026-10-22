"""
Documentation executability tests.

The README's headline snippet is the first code a prospective user runs, and a
snippet that raises is worse than no snippet at all. These tests extract the
fenced python blocks from the shipped docs and execute them, so a doc example
cannot rot unnoticed. They also pin the counts the docs advertise to the counts
the code actually produces.
"""

import re
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_FILES = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "SECURITY.md",
    *sorted((REPO_ROOT / "docs").glob("*.md")),
]


def _runnable_blocks():
    """Yields (doc_name, index, source) for every self-contained python block."""
    for doc in DOC_FILES:
        if not doc.exists():
            continue
        blocks = re.findall(r"```python\n(.*?)```", doc.read_text(), re.S)
        for index, block in enumerate(blocks):
            source = textwrap.dedent(block)
            # Blocks without an import are illustrative fragments quoted inside
            # prose (they assume an `rt` from the surrounding text), not scripts.
            if "import" not in source:
                continue
            yield doc.name, index, source


class TestDocumentedCountsMatchReality(unittest.TestCase):
    """The numbers in the docs are claims, so they get checked like claims."""

    def _readme(self) -> str:
        return (REPO_ROOT / "README.md").read_text()

    def test_the_advertised_unit_test_count_is_the_real_one(self):
        """A stale test count is a small lie in the first table a buyer reads."""
        loader = unittest.TestLoader()
        suite = loader.discover(str(REPO_ROOT / "tests"), top_level_dir=str(REPO_ROOT / "tests"))
        self.assertEqual(loader.errors, [], f"test discovery failed: {loader.errors}")
        actual = suite.countTestCases()
        self.assertIn(
            f"{actual} unit tests", self._readme(),
            f"README does not state the real test count of {actual}",
        )

    def test_the_advertised_audit_and_benchmark_counts_are_real(self):
        from modus_light import ModusLight
        from modus_light.cli import CAPABILITY_VECTORS

        checks = ModusLight().run_smoke_audit().checks_total
        self.assertIn(f"{checks} executable audit checks", self._readme())
        self.assertIn(f"{len(CAPABILITY_VECTORS)} executable capability vectors", self._readme())

    def test_no_stale_count_survives_anywhere_in_the_readme(self):
        """The table phrasing was locked, but the same numbers are quoted in
        prose too — and a wrong one there sat directly beneath the claim that
        every number in the README is measured by the code. Lock the count
        itself rather than one sentence that happens to contain it."""
        from modus_light import ModusLight
        from modus_light.cli import CAPABILITY_VECTORS

        checks = ModusLight().run_smoke_audit().checks_total
        vectors = len(CAPABILITY_VECTORS)
        readme = self._readme()
        for noun, real in (("checks", checks), ("assertions", vectors)):
            for stated in re.findall(rf"(\d+) real {noun}", readme):
                self.assertEqual(
                    int(stated), real,
                    f"README claims {stated} real {noun}; the code runs {real}",
                )


class TestDocumentedClaimsMatchTheCode(unittest.TestCase):
    """Numbers measured on a workstation cannot be asserted in CI without
    flaking, but the claims that are *structural* can be — and those are the
    ones that silently rot when the code moves."""

    def _docs(self):
        for name in ("README.md", "SECURITY.md"):
            path = REPO_ROOT / name
            if path.exists():
                yield name, path.read_text()
        for path in sorted((REPO_ROOT / "docs").glob("*.md")):
            yield f"docs/{path.name}", path.read_text()

    def test_the_stated_regression_gate_is_the_one_the_code_enforces(self):
        """The README tells the reader which latency gate fails the build. If
        the constant moves and the prose does not, the prose is marketing."""
        from modus_light.cli import DISPATCH_BUDGET_MS

        readme = (REPO_ROOT / "README.md").read_text()
        self.assertIn(
            f"{DISPATCH_BUDGET_MS} ms regression gate", readme,
            f"README must state the real gate of {DISPATCH_BUDGET_MS} ms",
        )

    def test_every_audit_count_phrasing_in_the_docs_is_the_real_one(self):
        """Three different phrasings of the same number have now gone stale in
        turn ("16 executable audit checks", "15 real checks", "15-point
        compliance audit"), so the lock matches the number next to the word
        rather than any one sentence."""
        from modus_light import ModusLight

        real = ModusLight().run_smoke_audit().checks_total
        pattern = re.compile(
            r"(\d+)[\s-]*(?:executable |real |point |compliance )*"
            r"(?:audit check|check|point compliance audit|compliance audit)",
            re.IGNORECASE,
        )
        for name, text in self._docs():
            for raw in pattern.finditer(text):
                stated = int(raw.group(1))
                # Only a figure in the plausible range is this claim; counts
                # like "5 core engines" or a year are not.
                if 5 <= stated <= 99 and stated != real:
                    self.fail(
                        f"{name} states {stated} audit checks; the code runs {real}: "
                        f"...{text[max(0, raw.start() - 40):raw.end() + 20]}..."
                    )

    def test_every_internal_readme_anchor_resolves(self):
        """A dead in-page link is the cheapest possible broken promise, and the
        CI-status section is now linked from the scope table."""
        readme = (REPO_ROOT / "README.md").read_text()
        slugs = set()
        in_fence = False
        for line in readme.splitlines():
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not re.match(r"#+\s", line):
                continue
            # GitHub's rule: lowercase, drop anything that is not a word
            # character, space, hyphen or underscore, then spaces to hyphens.
            # It does *not* trim first, so the space left behind by a stripped
            # leading emoji becomes a leading hyphen — which is why several
            # real anchors in this file start with one.
            title = re.sub(r"^#+\s", "", line).lower()
            slugs.add(re.sub(r"[^\w\s-]", "", title).replace(" ", "-"))
        for target in re.findall(r"\]\(#([^)]+)\)", readme):
            self.assertIn(
                target, slugs, f"README links to #{target}, which no heading produces",
            )

    def test_the_published_token_reduction_table_is_the_measured_one(self):
        """
        The token saving is the claim most worth faking, so the README's table
        is regenerated here and compared row by row. A figure that drifts from
        the meter fails the build.
        """
        from modus_light.cli import TOKEN_REPORT_HOPS
        from modus_light.token_meter import DEFAULT_PIPELINE, measure_token_reduction

        readme = (REPO_ROOT / "README.md").read_text()
        for hops in TOKEN_REPORT_HOPS:
            repeats = max(1, hops // len(DEFAULT_PIPELINE))
            result = measure_token_reduction(repeats=repeats)
            row = (
                f"| {result.hops} | {result.conversational_tokens:,} | "
                f"{result.tuple_space_tokens:,} | **{result.reduction_pct:.1f}%** |"
            )
            self.assertIn(
                row, readme,
                f"README is missing the measured row for {result.hops} hops:\n  {row}",
            )

    def test_no_doc_claims_a_token_reduction_the_meter_does_not_support(self):
        """
        A reduction figure means nothing without the pipeline length it was
        measured at: this runtime saves 14.7% over five hops and 95.2% over a
        hundred, so a bare percentage is not a claim, it is a mood. Every one of
        them has to appear alongside its hop count — including the conservative
        ones, since a rule with exceptions is how an unqualified headline number
        gets in.
        """
        from modus_light.token_meter import measure_token_reduction

        measure_token_reduction(repeats=20)  # the meter must be callable at all
        for name, text in self._docs():
            for match in re.finditer(r"(\d{2}(?:\.\d)?)\s*% reduction", text):
                stated = float(match.group(1))
                window = text[max(0, match.start() - 250):match.end() + 250]
                self.assertRegex(
                    window, r"hop|pipeline length",
                    f"{name} states a {stated}% token reduction without naming the "
                    f"pipeline length it applies to — this runtime's reduction ranges "
                    f"from 14.7% to 95.2% with hop count, so the figure alone says "
                    f"nothing",
                )

    def test_the_advertised_python_versions_are_the_supported_ones(self):
        """The badge is the first thing a stranger reads. It has to agree with
        `requires-python` and the classifiers, or someone installs on a version
        nobody tested."""
        pyproject = (REPO_ROOT / "pyproject.toml").read_text()
        classified = set(re.findall(r"Programming Language :: Python :: (3\.\d+)", pyproject))
        self.assertTrue(classified, "no Python version classifiers found")

        readme = (REPO_ROOT / "README.md").read_text()
        badged = set(re.findall(r"3\.\d+", re.search(r"badge/python-([^-]+)-blue", readme).group(1)))
        self.assertEqual(
            badged, classified,
            f"README badge advertises {sorted(badged)}; pyproject classifies {sorted(classified)}",
        )

        floor = min(classified, key=lambda v: tuple(map(int, v.split("."))))
        self.assertIn(f'requires-python = ">={floor}"', pyproject)

    def test_the_zero_dependency_claim_is_literally_true(self):
        """It is the first promise in the README and the whole basis of the
        air-gap story, so it is checked against the manifest rather than
        trusted."""
        pyproject = (REPO_ROOT / "pyproject.toml").read_text()
        self.assertIn("dependencies = []", pyproject)

    def test_no_doc_calls_the_round_trip_sub_millisecond_under_load(self):
        """It is not: the round trip is O(n) in backlog depth and passes a
        millisecond at roughly 2,500 resident tuples. This claim was published
        once and is banned rather than left to a reviewer's memory."""
        for name, text in self._docs():
            for line in text.splitlines():
                if "sub-millisecond under load" in line and "not " not in line:
                    self.fail(f"{name} claims the round trip is sub-millisecond under load: {line[:120]}")


class TestDocumentedExamplesExecute(unittest.TestCase):

    def test_at_least_one_block_is_discovered(self):
        """Guards against the regex silently matching nothing."""
        self.assertGreater(len(list(_runnable_blocks())), 0)

    def test_every_self_contained_block_runs_clean(self):
        for doc_name, index, source in _runnable_blocks():
            with self.subTest(doc=doc_name, block=index):
                result = subprocess.run(
                    [sys.executable, "-c", source],
                    capture_output=True,
                    text=True,
                    cwd=REPO_ROOT,
                )
                self.assertEqual(
                    result.returncode, 0,
                    f"{doc_name} python block #{index} failed:\n{result.stderr}",
                )


if __name__ == "__main__":
    unittest.main()
