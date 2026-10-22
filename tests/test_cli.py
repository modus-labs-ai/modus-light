"""
Tests for the Modus Light CLI entry points
"""

import io
import os
import pathlib
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from modus_light import cli


class TestModusLightCli(unittest.TestCase):

    def _run(self, func, *args):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = func(*args)
        return result, buffer.getvalue()

    def test_demo_runs_end_to_end(self):
        """The demo is the first thing a new user runs, so it must execute
        end to end rather than raising partway through."""
        result, output = self._run(cli.run_demo)
        self.assertIsNone(result)
        self.assertIn("Test Drive Completed Successfully", output)
        self.assertIn("Step 6/6", output)

    def test_demo_shows_real_refusals(self):
        _result, output = self._run(cli.run_demo)
        self.assertIn("Zanzibar ReBAC Refusal", output)
        self.assertIn("Step 5 FinOps Kill Switch Tripped", output)

    def test_benchmark_reports_no_failures(self):
        result, output = self._run(cli.run_benchmark)
        self.assertEqual(result, 0)
        self.assertIn("10/10 CAPABILITY VECTORS PASSED", output)
        self.assertNotIn("[FAIL]", output)

    def test_audit_passes_and_reports_checks(self):
        _result, output = self._run(cli.run_audit)
        self.assertIn("16/16 PASSED", output)
        self.assertIn("Status:", output)

    def test_token_report_runs_and_reports_a_measured_reduction(self):
        """The token report is the ROI claim, so it has to execute rather than
        print a stored table."""
        result, output = self._run(cli.run_token_report)
        self.assertEqual(result, 0)
        self.assertIn("MEASURED TOKEN REDUCTION", output)
        self.assertIn("95.2%", output)
        self.assertIn("14.7%", output)

    def test_info_matrix_renders(self):
        _result, output = self._run(cli.show_info)
        self.assertIn("MODUS LIGHT (COMMUNITY)", output)


class TestTheCliSurvivesHostileOutputStreams(unittest.TestCase):
    """The CLI prints non-ASCII status glyphs and ANSI colour. Neither may
    depend on the destination being a UTF-8 terminal: the package advertises
    `Operating System :: OS Independent`, and the most common way to run a
    compliance audit is to redirect it into a file."""

    COMMANDS = ("demo", "audit", "benchmark", "info", "tokens")

    def _run(self, args, **env_overrides):
        env = dict(os.environ)
        env.pop("NO_COLOR", None)
        # Derive the import root from the already-imported package rather than
        # assuming the caller's cwd or PYTHONPATH, so these subprocess tests
        # pass under `make test`, a bare `unittest discover`, and an installed
        # wheel alike.
        import modus_light
        src_root = str(pathlib.Path(modus_light.__file__).resolve().parent.parent)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_root}{os.pathsep}{existing}" if existing else src_root
        env.update(env_overrides)
        return subprocess.run(
            [sys.executable, "-m", "modus_light", *args],
            capture_output=True, text=True, env=env, timeout=300,
        )

    def test_every_command_survives_an_ascii_only_stream(self):
        """`PYTHONIOENCODING=ascii` is the portable stand-in for Windows
        cp1252: before the fix, every command died with UnicodeEncodeError
        *after* the work had already succeeded, turning a passing audit into a
        non-zero exit."""
        for command in self.COMMANDS:
            with self.subTest(command=command):
                result = self._run([command], PYTHONIOENCODING="ascii")
                self.assertEqual(
                    result.returncode, 0,
                    f"{command} failed on an ascii stream: {result.stderr[-500:]}",
                )
                self.assertNotIn("UnicodeEncodeError", result.stderr)

    def test_no_escape_sequences_when_output_is_not_a_terminal(self):
        """`capture_output` makes stdout a pipe, which is what a CI log or a
        `tee` is. Escape codes there are noise that breaks log greps."""
        result = self._run(["audit"])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("\033[", result.stdout)
        self.assertIn("PASSED", result.stdout)

    def test_no_color_is_honoured(self):
        """https://no-color.org — an environment variable, not a flag, because
        users set it once for every tool they run."""
        result = self._run(["info"], NO_COLOR="1")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("\033[", result.stdout)

    def test_the_module_is_runnable_without_the_console_script(self):
        """`pip install --user`, or an unactivated venv, leaves the
        `modus-light` script off PATH. `python -m modus_light` must still work,
        and every test in this class already depends on it."""
        result = self._run(["--version"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("modus-light", result.stdout)

    def test_version_reports_the_installed_package_version(self):
        from modus_light import __version__
        result = self._run(["--version"])
        self.assertIn(__version__, result.stdout)


if __name__ == "__main__":
    unittest.main()
