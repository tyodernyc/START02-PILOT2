import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GREET = os.path.join(HERE, "greet.py")


def run_greet(arguments, **options):
    """Run greet.py as a separate process and capture both output streams."""
    options.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.run(
        [sys.executable, GREET] + list(arguments),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **options,
    )


class GreetTestCase(unittest.TestCase):
    def assert_greets(self, arguments, expected, **options):
        """Standard output is compared as bytes; exit status 0; no error output."""
        result = run_greet(arguments, **options)
        self.assertEqual(
            (result.stdout, result.returncode, result.stderr),
            (expected, 0, b""),
        )


class TestGreet(GreetTestCase):
    """Criteria C1 to C9: one test for each row of the table."""

    def test_no_name(self):  # C1
        self.assert_greets([], b"Hello.\n")

    def test_one_name(self):  # C2
        self.assert_greets(["Ana"], b"Hello, Ana.\n")

    def test_two_arguments(self):  # C3
        self.assert_greets(["Ana", "Maria"], b"Hello, Ana Maria.\n")

    def test_empty_name(self):  # C4
        self.assert_greets([""], b"Hello.\n")

    def test_blank_name(self):  # C5
        self.assert_greets(["   "], b"Hello.\n")

    def test_trimmed_name(self):  # C6
        self.assert_greets([" Ana "], b"Hello, Ana.\n")

    def test_non_ascii_name(self):  # C7
        self.assert_greets(["José"], b"Hello, Jos\xc3\xa9.\n")

    def test_hyphen_name(self):  # C8
        self.assert_greets(["-n"], b"Hello, -n.\n")

    def test_brace_name(self):  # C9
        self.assert_greets(["{0}"], b"Hello, {0}.\n")


class TestGreetFurtherChecks(GreetTestCase):
    """The two further checks of R18."""

    def test_case_is_kept(self):
        self.assert_greets(["ana"], b"Hello, ana.\n")

    def test_standard_input_and_environment_are_ignored(self):
        environment = dict(os.environ, GREET_NAME="Bob")
        self.assert_greets(
            [], b"Hello.\n", stdin=None, input=b"Bob\n", env=environment
        )


@unittest.skipIf(os.name == "nt", "needs POSIX process arguments and descriptors")
class TestGreetAlwaysExitsCleanly(GreetTestCase):
    """R16, exit and error stream: status 0 and no error output, whatever
    the arguments. These go beyond the rows of the table."""

    def test_argument_that_is_not_valid_text(self):
        result = run_greet([b"\xff"])
        self.assertEqual((result.returncode, result.stderr), (0, b""))
        self.assertTrue(result.stdout.startswith(b"Hello, "), result.stdout)
        self.assertTrue(result.stdout.endswith(b".\n"), result.stdout)

    def test_closed_standard_output(self):
        result = subprocess.run(
            [sys.executable, GREET, "Ana"],
            stdin=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=lambda: os.close(1),
        )
        self.assertEqual((result.returncode, result.stderr), (0, b""))


if __name__ == "__main__":
    unittest.main()
