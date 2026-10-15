import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


class TestGreet(unittest.TestCase):
    def test_output(self):
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "greet.py")],
            capture_output=True,
            check=True,
        )
        self.assertEqual(result.stdout, b"START-02 pilot: reviewed, merged and reversible.\n")


if __name__ == "__main__":
    unittest.main()
