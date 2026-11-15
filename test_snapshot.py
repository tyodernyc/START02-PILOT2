"""Tests for snapshot.py (build request #54).

Every check V1 to V6 of build request #54 has at least one test method named
after it. Each case runs the program as a separate process and compares
standard output, standard error and the exit status. The tests named
test_extra_* cover the rest of the specification.
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "snapshot.py")
MERGE_CHECK = os.path.join(HERE, "merge_check.py")
ERROR_PREFIX = b"snapshot: "
USAGE = (
    b"snapshot: usage: python snapshot.py PULL FILES CHECKS ISSUE_COMMENTS REVIEW_COMMENTS ALLOWED"
    b" [--required-checks NAME,NAME] [--protected PREFIX,PREFIX]\n"
)

H = "0123456789abcdef0123456789abcdef01234567"
CLAUDE = "claude[bot]"
CODEX = "chatgpt-codex-connector[bot]"
NAMES = ("pull", "files", "checks", "issues", "reviews", "allowed")
ARGUMENTS = {
    "pull": "PULL",
    "files": "FILES",
    "checks": "CHECKS",
    "issues": "ISSUE_COMMENTS",
    "reviews": "REVIEW_COMMENTS",
    "allowed": "ALLOWED",
}


def run_check(run_id, name, status="completed", conclusion="success"):
    return {"id": run_id, "name": name, "status": status, "conclusion": conclusion}


def comment(comment_id, login, body):
    return {"id": comment_id, "user": {"login": login}, "body": body}


def sample():
    """Five small sample files (as Python values) and the text of the ALLOWED file."""
    return {
        "pull": {
            "number": 7,
            "state": "open",
            "draft": False,
            "head": {"sha": H},
            "body": "## Summary\nOne thing.\n\n## Open questions\nnone\n",
        },
        "files": [{"filename": "snapshot.py"}, {"filename": "test_snapshot.py"}],
        "checks": {"total_count": 2, "check_runs": [run_check(1, "tests"), run_check(2, "review")]},
        "issues": [
            comment(1, CLAUDE, "## Automatic review\nHEAD: %s\nVERDICT: PASS\nBLOCKING:\n- none" % H),
            comment(2, CODEX, "Codex Review: Didn't find any major issues.\n\nReviewed commit: `%s`" % H[:10]),
        ],
        "reviews": [],
        "allowed": "# the paths this request may change\nsnapshot.py\n\ntest_snapshot.py\n",
    }


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def write_input(directory, name, value):
    path = os.path.join(directory, name)
    if name == "allowed":
        write_text(path, value)
    else:
        write_text(path, json.dumps(value))
    return path


def run_program(program, args):
    done = subprocess.run([sys.executable, "-I", program] + args, capture_output=True)
    return done.stdout, done.stderr, done.returncode


class Case(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.dir = holder.name

    def paths(self, **replace):
        """Write the sample files, with some replaced; return the six paths in order."""
        values = sample()
        values.update(replace)
        return [write_input(self.dir, name, values[name]) for name in NAMES]

    def snapshot(self, extra=None, **replace):
        out, err, status = run_program(PROGRAM, self.paths(**replace) + (extra or []))
        self.assertEqual((err, status), (b"", 0))
        self.assertTrue(out.endswith(b"\n"))
        return json.loads(out)

    def merge_result(self, **replace):
        """Build a snapshot, save it, and return the line merge_check.py prints."""
        path = os.path.join(self.dir, "snapshot.json")
        out, err, status = run_program(PROGRAM, self.paths(**replace))
        self.assertEqual((err, status), (b"", 0))
        with open(path, "wb") as handle:
            handle.write(out)
        out, err, status = run_program(MERGE_CHECK, [path])
        self.assertEqual((err, status), (b"", 0))
        return out.decode("utf-8")


class TestV1(Case):
    def test_v1_merge(self):
        self.assertEqual(self.merge_result(), "MERGE\n")

    def test_v1_file_outside_allowed(self):
        files = sample()["files"] + [{"filename": "other.py"}]
        self.assertEqual(self.merge_result(files=files), "OWNER: paths\n")

    def test_v1_output_keys(self):
        data = self.snapshot()
        self.assertEqual(
            sorted(data),
            ["allowed", "check_runs", "files", "issue_comments", "pull", "review_comments"],
        )
        values = sample()
        self.assertEqual(data["pull"], values["pull"])
        self.assertEqual(data["files"], values["files"])
        self.assertEqual(data["check_runs"], values["checks"])
        self.assertEqual(data["issue_comments"], values["issues"])
        self.assertEqual(data["review_comments"], [])
        self.assertEqual(data["allowed"], ["snapshot.py", "test_snapshot.py"])


class TestV2(Case):
    def test_v2_files_pages_joined_in_order(self):
        pages = [[{"filename": "a.py"}, {"filename": "b.py"}], [{"filename": "c.py"}]]
        self.assertEqual(
            self.snapshot(files=pages)["files"],
            [{"filename": "a.py"}, {"filename": "b.py"}, {"filename": "c.py"}],
        )

    def test_v2_comment_pages_joined_in_order(self):
        issues = [[comment(1, "a", "x")], [], [comment(2, "b", "y")]]
        reviews = [[comment(3, "a", "z")], [comment(4, "b", "w")]]
        data = self.snapshot(issues=issues, reviews=reviews)
        self.assertEqual([item["id"] for item in data["issue_comments"]], [1, 2])
        self.assertEqual([item["id"] for item in data["review_comments"]], [3, 4])

    def test_v2_one_page_and_empty_lists(self):
        self.assertEqual(self.snapshot(files=[])["files"], [])
        self.assertEqual(self.snapshot(files=[[]])["files"], [])
        self.assertEqual(self.snapshot(files=[[], []])["files"], [])

    def test_v2_check_pages_joined_in_order(self):
        pages = [
            {"total_count": 3, "check_runs": [run_check(1, "tests"), run_check(2, "review")]},
            {"total_count": 3, "check_runs": [run_check(3, "extra")]},
        ]
        data = self.snapshot(checks=pages)
        self.assertEqual(data["check_runs"]["total_count"], 3)
        self.assertEqual([item["id"] for item in data["check_runs"]["check_runs"]], [1, 2, 3])

    def test_v2_check_total_count_from_first_page(self):
        pages = [
            {"total_count": 5, "check_runs": [run_check(1, "tests")]},
            {"total_count": 9, "check_runs": [run_check(2, "review")]},
        ]
        data = self.snapshot(checks=pages)
        self.assertEqual(data["check_runs"]["total_count"], 5)
        self.assertEqual(self.merge_result(checks=pages), "OWNER: checks\n")

    def test_v2_check_without_total_count(self):
        data = self.snapshot(checks={"check_runs": [run_check(1, "tests")]})
        self.assertEqual(data["check_runs"], {"check_runs": [run_check(1, "tests")]})


class TestV3(Case):
    def test_v3_required_checks(self):
        data = self.snapshot(["--required-checks", "ci,review"])
        self.assertEqual(data["required_checks"], ["ci", "review"])
        self.assertIn(b'"required_checks": ["ci", "review"]', self.raw(["--required-checks", "ci,review"]))

    def raw(self, extra):
        out, err, status = run_program(PROGRAM, self.paths() + extra)
        self.assertEqual((err, status), (b"", 0))
        return out

    def test_v3_absent_without_option(self):
        data = self.snapshot()
        self.assertNotIn("required_checks", data)
        self.assertNotIn("protected", data)

    def test_v3_required_checks_reach_merge_check(self):
        path = os.path.join(self.dir, "snapshot.json")
        out, _, _ = run_program(PROGRAM, self.paths() + ["--required-checks", "ci,review"])
        with open(path, "wb") as handle:
            handle.write(out)
        out, err, status = run_program(MERGE_CHECK, [path])
        self.assertEqual((out, err, status), (b"OWNER: checks\n", b"", 0))

    def test_v3_protected(self):
        data = self.snapshot(["--protected", "src/,Makefile"])
        self.assertEqual(data["protected"], ["src/", "Makefile"])
        self.assertNotIn("required_checks", data)

    def test_v3_both_options_in_either_order(self):
        data = self.snapshot(["--protected", "a/", "--required-checks", "tests"])
        self.assertEqual((data["protected"], data["required_checks"]), (["a/"], ["tests"]))

    def test_v3_options_before_the_files(self):
        out, err, status = run_program(PROGRAM, ["--required-checks", "x"] + self.paths())
        self.assertEqual((err, status), (b"", 0))
        self.assertEqual(json.loads(out)["required_checks"], ["x"])

    def test_v3_protected_reaches_merge_check(self):
        files = sample()["files"]
        allowed = "snapshot.py\ntest_snapshot.py\n"
        path = os.path.join(self.dir, "snapshot.json")
        out, _, _ = run_program(PROGRAM, self.paths(files=files, allowed=allowed) + ["--protected", "snapshot.py"])
        with open(path, "wb") as handle:
            handle.write(out)
        out, err, status = run_program(MERGE_CHECK, [path])
        self.assertEqual((out, err, status), (b"OWNER: protected\n", b"", 0))

    def test_v3_empty_name_is_bad(self):
        for option in ("--required-checks", "--protected"):
            for value in ("", "a,", ",a", "a,,b"):
                out, err, status = run_program(PROGRAM, self.paths() + [option, value])
                self.assertEqual(out, b"")
                self.assertEqual(status, 2)
                self.assertEqual(
                    err,
                    ERROR_PREFIX + option.encode() + b" must be a comma-separated list of non-empty names\n",
                )


    def test_v3_spaced_name_is_bad(self):
        for option in ("--required-checks", "--protected"):
            for value in ("a, b", " a", "a ", "a,\tb"):
                out, err, status = run_program(PROGRAM, self.paths() + [option, value])
                self.assertEqual(out, b"")
                self.assertEqual(status, 2)
                self.assertEqual(err, ERROR_PREFIX + option.encode() + b" must not have spaces around a name\n")

    def test_v3_repeated_name_is_bad(self):
        for option in ("--required-checks", "--protected"):
            out, err, status = run_program(PROGRAM, self.paths() + [option, "tests,tests,review"])
            self.assertEqual(out, b"")
            self.assertEqual(status, 2)
            self.assertEqual(err, ERROR_PREFIX + option.encode() + b" must not repeat a name\n")


class TestV4(Case):
    def files(self, count):
        return [{"filename": "f%d.py" % number} for number in range(count)]

    def test_v4_3000_files_truncated(self):
        data = self.snapshot(files=self.files(3000))
        self.assertIs(data["files_truncated"], True)
        self.assertEqual(len(data["files"]), 3000)

    def test_v4_2999_files_not_truncated(self):
        data = self.snapshot(files=self.files(2999))
        self.assertNotIn("files_truncated", data)
        self.assertEqual(len(data["files"]), 2999)

    def test_v4_count_is_over_the_joined_pages(self):
        pages = [self.files(1500), self.files(1500)]
        self.assertIs(self.snapshot(files=pages)["files_truncated"], True)
        pages = [self.files(1500), self.files(1499)]
        self.assertNotIn("files_truncated", self.snapshot(files=pages))

    def test_v4_truncated_gives_owner_paths(self):
        allowed = "*\n"
        self.assertEqual(self.merge_result(files=self.files(3000), allowed=allowed), "OWNER: paths\n")
        self.assertEqual(self.merge_result(files=self.files(2999), allowed=allowed), "MERGE\n")


class TestV5(Case):
    def bad(self, name, content, message):
        """Replace one input file by the content; expect exit 2 and the exact message."""
        paths = self.paths()
        write_text(paths[NAMES.index(name)], content)
        out, err, status = run_program(PROGRAM, paths)
        self.assertEqual(out, b"")
        self.assertEqual(status, 2)
        self.assertEqual(err, ERROR_PREFIX + message.encode() + b"\n")
        self.assertIn(ARGUMENTS[name].encode(), err)

    def test_v5_non_json_in_each_argument(self):
        for name in NAMES[:-1]:
            self.bad(name, "not json", ARGUMENTS[name] + " is not UTF-8 JSON")
            self.bad(name, "", ARGUMENTS[name] + " is not UTF-8 JSON")

    def test_v5_allowed_only_comments_and_blank_lines(self):
        for text in ("", "\n", "# one\n\n   \n#two\n", "\r\n# x\r\n"):
            self.bad("allowed", text, "ALLOWED holds no path pattern")

    def test_v5_nan_and_infinity(self):
        for name in NAMES[:-1]:
            for constant in ("NaN", "Infinity", "-Infinity"):
                self.bad(
                    name,
                    '{"x": %s}' % constant if name in ("pull", "checks") else "[%s]" % constant,
                    "%s holds %s, which is not JSON" % (ARGUMENTS[name], constant),
                )

    def test_v5_wrong_shape(self):
        self.bad("pull", "[]", "PULL must be a JSON object")
        self.bad("pull", '"text"', "PULL must be a JSON object")
        lists = " must be a JSON array of objects or an array of such arrays"
        for name in ("files", "issues", "reviews"):
            for content in ("{}", "3", '["a"]', "[1]", "[[1]]", '[[{}], "a"]', "[{}, []]", "[[], {}]", "null"):
                self.bad(name, content, ARGUMENTS[name] + lists)
        checks = " must be a check-runs JSON object or an array of such objects"
        for content in (
            "[]",
            "[[]]",
            "3",
            "{}",
            '{"check_runs": {}}',
            '{"check_runs": [1]}',
            '{"check_runs": [], "total_count": "2"}',
            '{"check_runs": [], "total_count": true}',
            '[{"check_runs": []}, 3]',
            '[{"check_runs": []}, {}]',
        ):
            self.bad("checks", content, "CHECKS" + checks)

    def test_v5_number_too_large_for_json(self):
        # 1e999 is a JSON number that Python reads as infinity; it must not come out as Infinity.
        for name in NAMES[:-1]:
            for number in ("1e999", "-1e999", "1E+400"):
                self.bad(
                    name,
                    '{"x": %s}' % number if name in ("pull", "checks") else "[%s]" % number,
                    ARGUMENTS[name] + " holds a number too large for JSON",
                )
        self.bad("pull", '{"x": [1, {"y": 1e999}]}', "PULL holds a number too large for JSON")

    def test_v5_large_but_finite_numbers_pass(self):
        paths = self.paths()
        write_text(paths[0], '{"x": 1e308, "y": -1e308, "z": 1e-999, "w": 2.5}')
        out, err, status = run_program(PROGRAM, paths)
        self.assertEqual((err, status), (b"", 0))
        self.assertEqual(json.loads(out)["pull"], {"x": 1e308, "y": -1e308, "z": 0.0, "w": 2.5})
        self.assertNotIn(b"Infinity", out)
        self.assertNotIn(b"NaN", out)

    def test_v5_unreadable_file(self):
        for index, name in enumerate(NAMES):
            paths = self.paths()
            paths[index] = os.path.join(self.dir, "missing.json")
            out, err, status = run_program(PROGRAM, paths)
            self.assertEqual((out, status), (b"", 2))
            self.assertEqual(err, ERROR_PREFIX + b"cannot read " + ARGUMENTS[name].encode() + b"\n")
        paths = self.paths()
        paths[0] = self.dir  # a directory
        out, err, status = run_program(PROGRAM, paths)
        self.assertEqual((out, err, status), (b"", ERROR_PREFIX + b"cannot read PULL\n", 2))

    def test_v5_not_utf8(self):
        for name in NAMES:
            paths = self.paths()
            with open(paths[NAMES.index(name)], "wb") as handle:
                handle.write(b"\xff\xfe[]\n" if name != "allowed" else b"a.py\n\xff\n")
            out, err, status = run_program(PROGRAM, paths)
            self.assertEqual((out, status), (b"", 2))
            self.assertEqual(err, ERROR_PREFIX + ARGUMENTS[name].encode() + b" is not UTF-8\n")

    def test_v5_first_wrong_argument_is_named(self):
        paths = self.paths()
        write_text(paths[3], "x")
        write_text(paths[1], "x")
        out, err, status = run_program(PROGRAM, paths)
        self.assertEqual((out, err, status), (b"", ERROR_PREFIX + b"FILES is not UTF-8 JSON\n", 2))

    def test_v5_too_deep(self):
        paths = self.paths()
        write_text(paths[0], "[" * 100000 + "]" * 100000)
        out, err, status = run_program(PROGRAM, paths)
        self.assertEqual((out, err, status), (b"", ERROR_PREFIX + b"PULL is not UTF-8 JSON\n", 2))


class TestV6(unittest.TestCase):
    def test_v6_existing_tests_are_still_there(self):
        for name in (
            "test_merge_check.py",
            "test_next_request.py",
            "test_request_status.py",
            "test_gate.py",
            "test_greet.py",
            "test_attention.py",
            "test_affected_tests.py",
            "test_draft_followup.py",
        ):
            self.assertTrue(os.path.exists(os.path.join(HERE, name)), name)

    def test_v6_merge_check_is_not_changed_by_this_program(self):
        with open(MERGE_CHECK, "rb") as handle:
            before = handle.read()
        with tempfile.TemporaryDirectory() as directory:
            paths = [write_input(directory, name, sample()[name]) for name in NAMES]
            run_program(PROGRAM, paths)
        with open(MERGE_CHECK, "rb") as handle:
            self.assertEqual(handle.read(), before)


class TestExtra(Case):
    def test_extra_no_arguments(self):
        out, err, status = run_program(PROGRAM, [])
        self.assertEqual((out, err, status), (b"", USAGE, 2))

    def test_extra_wrong_argument_counts(self):
        paths = self.paths()
        for args in (paths[:5], paths + ["extra"], ["--protected", "a"] + paths[:5]):
            out, err, status = run_program(PROGRAM, args)
            self.assertEqual((out, err, status), (b"", USAGE, 2))

    def test_extra_wrong_options(self):
        paths = self.paths()
        for extra in (
            ["--required-checks"],
            ["--protected"],
            ["--other", "x"],
            ["--required-checks", "a", "--required-checks", "b"],
            ["--protected", "a", "--protected", "b"],
            ["--required-checks=a"],
        ):
            out, err, status = run_program(PROGRAM, paths + extra)
            self.assertEqual((out, err, status), (b"", USAGE, 2))

    def test_extra_allowed_lines(self):
        text = "﻿# comment\r\n  a.py  \r\n\r\n#b.py\nsrc/*.py\n\n"
        data = self.snapshot(allowed=text.replace("﻿", ""))
        self.assertEqual(data["allowed"], ["a.py", "src/*.py"])

    def test_extra_allowed_keeps_order_and_duplicates(self):
        self.assertEqual(self.snapshot(allowed="b\na\nb\n")["allowed"], ["b", "a", "b"])

    def test_extra_output_is_one_json_line(self):
        out, err, status = run_program(PROGRAM, self.paths())
        self.assertEqual((err, status), (b"", 0))
        self.assertEqual(out.count(b"\n"), 1)
        self.assertTrue(out.endswith(b"\n"))
        self.assertTrue(out.isascii())

    def test_extra_non_ascii_text_survives(self):
        files = [{"filename": "café/\U0001f600.py"}]
        data = self.snapshot(files=files, allowed="café/*\n")
        self.assertEqual(data["files"], files)
        self.assertEqual(data["allowed"], ["café/*"])

    def test_extra_pull_is_passed_through_unchecked(self):
        pull = {"number": "seven", "extra": [1, 2.5, None, True]}
        self.assertEqual(self.snapshot(pull=pull)["pull"], pull)

    def test_extra_huge_integer(self):
        paths = self.paths()
        digits = "9" * 6000
        write_text(paths[0], '{"number": %s}' % digits)
        out, err, status = run_program(PROGRAM, paths)
        self.assertEqual((err, status), (b"", 0))
        self.assertTrue(out.startswith(('{"pull": {"number": %s}, ' % digits).encode()))

    def test_extra_same_file_for_two_arguments(self):
        paths = self.paths()
        paths[4] = paths[3]
        out, err, status = run_program(PROGRAM, paths)
        self.assertEqual((err, status), (b"", 0))
        data = json.loads(out)
        self.assertEqual(data["review_comments"], data["issue_comments"])

    @unittest.skipUnless(os.path.exists("/dev/full"), "needs /dev/full")
    def test_extra_failed_write(self):
        with open("/dev/full", "wb") as full:
            done = subprocess.run([sys.executable, "-I", PROGRAM] + self.paths(), stdout=full, stderr=subprocess.PIPE)
        self.assertEqual((done.returncode, done.stderr), (1, ERROR_PREFIX + b"cannot write the snapshot\n"))

    def test_extra_standard_library_only(self):
        with open(PROGRAM, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add((node.module or "").split(".")[0])
        self.assertEqual(modules, {"json", "os", "sys"})


if __name__ == "__main__":
    unittest.main()
