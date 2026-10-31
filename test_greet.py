import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GREET = os.path.join(HERE, "greet.py")


def run(*args):
    result = subprocess.run(
        [sys.executable, GREET] + list(args),
        capture_output=True,
        check=True,
    )
    return result.stdout


class TestGreet(unittest.TestCase):
    def test_no_argument_defaults_to_world(self):
        self.assertEqual(run(), b"Hello, World.\n")

    def test_one_name(self):
        self.assertEqual(run("Ada"), b"Hello, Ada.\n")

    def test_empty_argument_is_treated_as_missing(self):
        self.assertEqual(run(""), b"Hello, World.\n")

    def test_whitespace_only_argument_is_treated_as_missing(self):
        self.assertEqual(run("   "), b"Hello, World.\n")

    def test_two_arguments_are_both_used(self):
        self.assertEqual(run("Ada", "Lovelace"), b"Hello, Ada Lovelace.\n")


if __name__ == "__main__":
    unittest.main()
