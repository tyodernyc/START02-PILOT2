import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GREET = os.path.join(HERE, "greet.py")


def run_greet(*args, stdin_bytes=None, extra_env=None):
    """Run greet.py as a separate process and return the finished process."""
    env = None
    if extra_env is not None:
        env = dict(os.environ)
        env.update(extra_env)
    options = {"capture_output": True, "env": env}
    if stdin_bytes is None:
        options["stdin"] = subprocess.DEVNULL
    else:
        options["input"] = stdin_bytes
    return subprocess.run([sys.executable, GREET, *args], **options)


class TestGreet(unittest.TestCase):
    def check(self, result, expected_stdout):
        self.assertEqual(result.stdout, expected_stdout)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")

    def test_output(self):
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "greet.py")],
            capture_output=True,
            check=True,
        )
        self.assertEqual(result.stdout, b"Hello.\n")

    # C1
    def test_no_name(self):
        self.check(run_greet(), b"Hello.\n")

    # C2
    def test_one_name(self):
        self.check(run_greet("Ana"), b"Hello, Ana.\n")

    # C3
    def test_two_arguments(self):
        self.check(run_greet("Ana", "Maria"), b"Hello, Ana Maria.\n")

    # C4
    def test_empty_name(self):
        self.check(run_greet(""), b"Hello.\n")

    # C5
    def test_blank_name(self):
        self.check(run_greet("   "), b"Hello.\n")

    # C6
    def test_trimmed_name(self):
        self.check(run_greet(" Ana "), b"Hello, Ana.\n")

    # C7
    def test_non_ascii_name(self):
        self.check(run_greet("José"), b"Hello, Jos\xc3\xa9.\n")

    # C8
    def test_hyphen_name(self):
        self.check(run_greet("-n"), b"Hello, -n.\n")

    # C9
    def test_brace_name(self):
        self.check(run_greet("{0}"), b"Hello, {0}.\n")

    # K1
    def test_case_kept(self):
        self.check(run_greet("ana"), b"Hello, ana.\n")

    # K2
    def test_ignores_stdin_and_environment(self):
        result = run_greet(
            stdin_bytes=b"Bob\n",
            extra_env={"GREET_NAME": "Bob"},
        )
        self.check(result, b"Hello.\n")


if __name__ == "__main__":
    unittest.main()
