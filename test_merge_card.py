"""Tests for merge_card.py (build request #56).

Checks V1 to V6 of build request #56 each have tests named after them. Every
case runs the program as a separate process and compares standard output,
standard error and the exit status exactly.
"""

import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "merge_card.py")
CHECKER = os.path.join(HERE, "merge_check.py")
ERROR = b"merge_card: bad input; usage: python merge_card.py TITLE < RESULT_LINE\n"

READY = (
    "Ready: every check passed, and the coordinator may merge it under the "
    "owner's standing conditions."
)

SENTENCES = [
    ("not-open", "It is closed or still a draft."),
    (
        "not-mergeable",
        "GitHub says it cannot be merged as it stands (for example it is "
        "behind the main line or has a conflict).",
    ),
    ("checks", "The required automatic checks have not all passed."),
    ("claude-review", "The Claude review has not passed this exact version."),
    ("codex-review", "Codex has not reviewed this exact version, or it found problems."),
    ("codex-p1", "Codex marked a serious problem on this version."),
    (
        "paths",
        "It changes files outside what the request allowed, or the list of "
        "changed files is incomplete.",
    ),
    (
        "protected",
        "It changes a protected area (the spec, the GitHub settings or the "
        "database design), which always needs the owner.",
    ),
    ("open-question", "It leaves a question open for the owner."),
]
SENTENCE = dict(SENTENCES)

H = "0123456789abcdef0123456789abcdef01234567"
CLAUDE = "claude[bot]"
CODEX = "chatgpt-codex-connector[bot]"


def run_card(*args, stdin=b""):
    return subprocess.run(
        [sys.executable, PROGRAM] + list(args),
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=HERE,
    )


def card(title, *lines):
    return ("\n".join(("Pull request: " + title,) + lines) + "\n").encode("utf-8")


class Case(unittest.TestCase):
    def good(self, title, stdin, expected):
        result = run_card(title, stdin=stdin)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)
        self.assertEqual(result.stderr, b"")

    def bad(self, *args, stdin=b"MERGE\n"):
        result = run_card(*args, stdin=stdin)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, ERROR)


class TestV1(Case):
    def test_v1_merge(self):
        self.good("Build request #7", b"MERGE\n", card("Build request #7", READY, "Next step: merge it."))

    def test_v1_merge_without_trailing_line_break(self):
        self.good("T", b"MERGE", card("T", READY, "Next step: merge it."))


class TestV2(Case):
    def test_v2_two_reasons_in_order(self):
        self.good(
            "Build request #7",
            b"OWNER: checks, protected\n",
            card(
                "Build request #7",
                "Needs the owner:",
                "- " + SENTENCE["checks"],
                "- " + SENTENCE["protected"],
                "Next step: the owner decides.",
            ),
        )

    def test_v2_order_is_the_order_given(self):
        self.good(
            "T",
            b"OWNER: protected, checks\n",
            card(
                "T",
                "Needs the owner:",
                "- " + SENTENCE["protected"],
                "- " + SENTENCE["checks"],
                "Next step: the owner decides.",
            ),
        )

    def test_v2_all_nine_codes_together(self):
        codes = [code for code, _ in SENTENCES]
        lines = ["Needs the owner:"] + ["- " + text for _, text in SENTENCES]
        lines.append("Next step: the owner decides.")
        self.good("T", ("OWNER: " + ", ".join(codes) + "\n").encode(), card("T", *lines))


class TestV3(Case):
    def test_v3_each_code_alone(self):
        for code, sentence in SENTENCES:
            with self.subTest(code=code):
                self.good(
                    "T",
                    ("OWNER: " + code + "\n").encode(),
                    card("T", "Needs the owner:", "- " + sentence, "Next step: the owner decides."),
                )


class TestV4(Case):
    def test_v4_bad_result_lines(self):
        for line in (
            b"OWNER: ",
            b"OWNER: checks,",
            b"OWNER: checks, checks",
            b"OWNER: unknown",
            b"merge",
            b"",
        ):
            with self.subTest(line=line):
                self.bad("T", stdin=line)
                self.bad("T", stdin=line + b"\n")

    def test_v4_more_bad_result_lines(self):
        for line in (
            b"OWNER:",
            b"OWNER:checks",
            b"OWNER: checks,protected",
            b"OWNER: checks , protected",
            b"OWNER: checks, ",
            b"OWNER: , checks",
            b"OWNER: checks,  protected",
            b"OWNER: Checks",
            b"owner: checks",
            b"MERGE ",
            b" MERGE",
            b"MERGE\n\n",
            b"MERGE\r\n",
            b"MERGE\nMERGE\n",
            b"MERGE, checks",
            b"OWNER: MERGE",
            b"OWNER: checks\nOWNER: protected\n",
            b"OWNER: checks\n\n",
            b"OWNER: checks\r\n",
            b"\n",
            b"\xff\xfe",
            b"OWNER: checks\xff",
            b"MERGE\x00",
        ):
            with self.subTest(line=line):
                self.bad("T", stdin=line)

    def test_v4_missing_title(self):
        self.bad()

    def test_v4_empty_title(self):
        self.bad("")

    def test_v4_title_with_line_break(self):
        for title in ("a\nb", "a\n", "\nb", "a\rb", "a\r\nb", "a b", "a\x0bb"):
            with self.subTest(title=title):
                self.bad(title)

    def test_v4_two_titles(self):
        self.bad("one", "two")

    def test_v4_bad_title_with_bad_result_is_still_status_2(self):
        self.bad("", stdin=b"merge")


class TestTitle(Case):
    def test_title_is_printed_as_given(self):
        for title in (
            "Build request #56: plain-English merge card",
            "  spaced  ",
            " ",
            "- starts with a dash",
            "Unicode: café ✓",
            "x" * 5000,
            "OWNER: checks",
            "MERGE",
        ):
            with self.subTest(title=title[:30]):
                self.good(title, b"MERGE\n", card(title, READY, "Next step: merge it."))

    def test_title_is_not_read_from_standard_input(self):
        self.bad(stdin=b"MERGE\n")


class TestOutputFailure(Case):
    def test_failed_write_exits_1(self):
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full not available")
        with open("/dev/full", "wb") as full:
            result = subprocess.run(
                [sys.executable, PROGRAM, "T"],
                input=b"MERGE\n",
                stdout=full,
                stderr=subprocess.PIPE,
                cwd=HERE,
            )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"merge_card: cannot write the result\n")

    def test_closed_standard_input_is_bad_input(self):
        result = subprocess.run(
            [sys.executable, PROGRAM, "T"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=HERE,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, ERROR)


def check_run(run_id, name):
    return {"id": run_id, "name": name, "status": "completed", "conclusion": "success"}


def comment(comment_id, login, body):
    return {"id": comment_id, "user": {"login": login}, "body": body}


def snapshot(**parts):
    """A small snapshot in which every merge_check rule passes."""
    data = {
        "pull": {
            "number": 7,
            "state": "open",
            "draft": False,
            "head": {"sha": H},
            "body": "## Summary\nOne thing.\n\n## Open questions\nnone\n",
        },
        "files": [{"filename": "merge_card.py"}, {"filename": "test_merge_card.py"}],
        "check_runs": {"check_runs": [check_run(1, "tests"), check_run(2, "review")]},
        "issue_comments": [
            comment(1, CLAUDE, "## Automatic review\nHEAD: %s\nVERDICT: PASS\nBLOCKING:\n- none" % H),
            comment(
                2,
                CODEX,
                "Codex Review: Didn't find any major issues.\n\nReviewed commit: `%s`" % H[:10],
            ),
        ],
        "review_comments": [],
        "allowed": ["merge_card.py", "test_merge_card.py"],
    }
    data.update(parts)
    return data


class TestV5(Case):
    def checker_output(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "snapshot.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            result = subprocess.run(
                [sys.executable, CHECKER, path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=folder,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_v5_real_merge_output(self):
        line = self.checker_output(snapshot())
        self.assertEqual(line, b"MERGE\n")
        self.good("Build request #56", line, card("Build request #56", READY, "Next step: merge it."))

    def test_v5_real_owner_output(self):
        data = snapshot(
            files=[{"filename": "merge_card.py"}, {"filename": ".github/workflows/x.yml"}],
            check_runs={"check_runs": [check_run(1, "tests")]},
        )
        line = self.checker_output(data)
        self.assertEqual(line, b"OWNER: checks, paths, protected\n")
        self.good(
            "Build request #56",
            line,
            card(
                "Build request #56",
                "Needs the owner:",
                "- " + SENTENCE["checks"],
                "- " + SENTENCE["paths"],
                "- " + SENTENCE["protected"],
                "Next step: the owner decides.",
            ),
        )

    def test_v5_real_output_piped_through_a_process_pipe(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "snapshot.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(snapshot(), handle)
            first = subprocess.Popen(
                [sys.executable, CHECKER, path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                cwd=folder,
            )
            second = subprocess.run(
                [sys.executable, PROGRAM, "Piped"],
                stdin=first.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=HERE,
            )
            first.stdout.close()
            self.assertEqual(first.wait(), 0)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout, card("Piped", READY, "Next step: merge it."))


class TestV6(Case):
    def test_v6_existing_tests_still_pass(self):
        # test_merge_check.py runs every other test module, this one included,
        # so it is left out here; running it would make the two call each other.
        skip = {os.path.basename(__file__), "test_merge_check.py"}
        modules = sorted(
            os.path.basename(path)[:-3]
            for path in glob.glob(os.path.join(HERE, "test_*.py"))
            if os.path.basename(path) not in skip
        )
        self.assertTrue(modules)
        result = subprocess.run(
            [sys.executable, "-m", "unittest"] + modules,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=HERE,
        )
        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", "replace")[-2000:])


if __name__ == "__main__":
    unittest.main()
