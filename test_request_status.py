"""Tests for request_status.py (build request #34).

Every numbered check T1 to T17 of the request has one test method named after
it. Each case runs the program as a separate process and compares standard
output, standard error and the exit status exactly. The tests named
test_extra_* cover the rest of the specification (S1 to S10).
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "request_status.py")
ERROR_PREFIX = b"request_status: "

H = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"

RESULTS = (
    "MERGED",
    "CLOSED",
    "DRAFT",
    "READY",
    "WAITING",
    "BLOCKED tests",
    "BLOCKED review",
    "BLOCKED tests review",
)


def pull(state="open", merged=False, draft=False, sha=H, **extra):
    """A pull request: open, not a draft, not merged, head H unless told otherwise."""
    item = {
        "number": 7,
        "title": "Some pull request",
        "state": state,
        "merged": merged,
        "draft": draft,
        "user": {"login": "someone"},
        "head": {"ref": "req-7", "sha": sha},
        "base": {"ref": "main", "sha": OTHER},
    }
    item.update(extra)
    return item


def pull_without(key):
    item = pull()
    del item[key]
    return item


def run(name, conclusion="success", status="completed", sha=H, run_id=None, **extra):
    """One check run: completed with conclusion success on H unless told otherwise."""
    item = {
        "id": run_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "head_sha": sha,
        "app": {"slug": "github-actions"},
    }
    item.update(extra)
    return item


def run_without(key, name="lint"):
    item = run(name, run_id=5)
    del item[key]
    return item


def checks(*runs, **extra):
    """The check runs of one commit; a run built without an id is given a fresh one."""
    listed = []
    for position, item in enumerate(runs):
        if type(item) is dict and "id" in item and item["id"] is None:
            item = dict(item, id=1000 + position)
        listed.append(item)
    document = {"total_count": len(listed), "check_runs": listed}
    document.update(extra)
    return document


def checks_without(key):
    document = checks(run("tests"), run("review"))
    del document[key]
    return document


BOTH = checks(run("tests"), run("review"))


def as_bytes(content):
    """File content: bytes are written as they are, anything else as JSON."""
    if isinstance(content, bytes):
        return content
    return json.dumps(content).encode("utf-8")


class ProgramCase(unittest.TestCase):
    def run_args(self, *args, env=None, stdout=subprocess.PIPE):
        return subprocess.run(
            [sys.executable, PROGRAM, *args],
            stdout=stdout,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env=env,
        )

    def run_files(self, pull_content, checks_content, env=None, stdout=subprocess.PIPE):
        with tempfile.TemporaryDirectory() as folder:
            pull_path = os.path.join(folder, "pull.json")
            checks_path = os.path.join(folder, "checks.json")
            with open(pull_path, "wb") as handle:
                handle.write(as_bytes(pull_content))
            with open(checks_path, "wb") as handle:
                handle.write(as_bytes(checks_content))
            return self.run_args(pull_path, checks_path, env=env, stdout=stdout)

    def assert_answer(self, result, expected):
        self.assertIn(expected, RESULTS)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout, expected.encode("ascii") + b"\n")
        self.assertEqual(result.returncode, 0)

    def assert_bad_input(self, result):
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith(ERROR_PREFIX), result.stderr)
        self.assertGreater(len(result.stderr), len(ERROR_PREFIX) + 1)
        self.assertTrue(result.stderr.endswith(b"\n"), result.stderr)
        self.assertEqual(result.stderr.count(b"\n"), 1, result.stderr)
        self.assertNotIn(b"\r", result.stderr)

    def assert_output_failed(self, result):
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b"Traceback", result.stderr)
        self.assertLessEqual(result.stderr.count(b"\n"), 1, result.stderr)


class TestNumberedChecks(ProgramCase):
    def test_t01_both_required_checks_succeed(self):
        self.assert_answer(self.run_files(pull(), BOTH), "READY")
        swapped = checks(run("review"), run("tests"))
        self.assert_answer(self.run_files(pull(), swapped), "READY")

    def test_t02_a_required_check_fails(self):
        cases = {
            "review failure": (
                checks(run("tests"), run("review", "failure")), "BLOCKED review"),
            "tests failure": (
                checks(run("tests", "failure"), run("review")), "BLOCKED tests"),
            "both failure, review listed first": (
                checks(run("review", "failure"), run("tests", "failure")),
                "BLOCKED tests review"),
            "both failure, tests listed first": (
                checks(run("tests", "failure"), run("review", "failure")),
                "BLOCKED tests review"),
        }
        for name, (document, expected) in cases.items():
            with self.subTest(case=name):
                self.assert_answer(self.run_files(pull(), document), expected)

    def test_t03_completed_without_success_blocks(self):
        conclusions = ("cancelled", "timed_out", "neutral", "skipped",
                       "action_required", "stale", None)
        for conclusion in conclusions:
            with self.subTest(conclusion=conclusion):
                document = checks(run("tests"), run("review", conclusion))
                self.assert_answer(self.run_files(pull(), document), "BLOCKED review")

    def test_t04_a_required_check_has_no_run(self):
        self.assert_answer(self.run_files(pull(), checks()), "WAITING")
        self.assert_answer(self.run_files(pull(), checks(run("tests"))), "WAITING")

    def test_t05_review_is_not_completed(self):
        for status in ("queued", "in_progress"):
            with self.subTest(status=status):
                document = checks(run("tests"), run("review", None, status))
                self.assert_answer(self.run_files(pull(), document), "WAITING")

    def test_t06_tests_fail_while_review_runs(self):
        document = checks(run("tests", "failure"), run("review", None, "in_progress"))
        self.assert_answer(self.run_files(pull(), document), "BLOCKED tests")

    def test_t07_the_highest_id_counts(self):
        tests = run("tests", run_id=3)
        cases = {
            "failure then success": ("failure", "success", "READY"),
            "success then failure": ("success", "failure", "BLOCKED review"),
        }
        for name, (first, second, expected) in cases.items():
            earlier = run("review", first, run_id=10)
            later = run("review", second, run_id=11)
            orders = {
                "earlier first": (tests, earlier, later),
                "later first": (tests, later, earlier),
                "later before tests": (later, tests, earlier),
            }
            for order, runs in orders.items():
                with self.subTest(case=name, order=order):
                    self.assert_answer(self.run_files(pull(), checks(*runs)), expected)

    def test_t08_runs_on_another_commit_do_not_count(self):
        elsewhere = checks(run("tests", sha=OTHER), run("review", sha=OTHER))
        self.assert_answer(self.run_files(pull(), elsewhere), "WAITING")
        for position in (0, 2):
            with self.subTest(position=position):
                runs = [run("tests", run_id=1), run("review", run_id=2)]
                runs.insert(position, run("review", "failure", sha=OTHER, run_id=99))
                self.assert_answer(self.run_files(pull(), checks(*runs)), "READY")

    def test_t09_names_are_matched_exactly(self):
        noise = checks(
            run("tests"),
            run("review"),
            run("Tests", "failure"),
            run("review ", "failure"),
            run("lint", "failure"),
        )
        self.assert_answer(self.run_files(pull(), noise), "READY")
        capitals = checks(run("Tests"), run("Review"))
        self.assert_answer(self.run_files(pull(), capitals), "WAITING")

    def test_t10_merged(self):
        failing = checks(run("tests", "failure"), run("review", "failure"))
        result = self.run_files(pull(state="closed", merged=True), failing)
        self.assert_answer(result, "MERGED")

    def test_t11_closed_without_merging(self):
        self.assert_answer(self.run_files(pull(state="closed"), BOTH), "CLOSED")

    def test_t12_draft(self):
        self.assert_answer(self.run_files(pull(draft=True), BOTH), "DRAFT")

    def test_t13_arguments_and_unreadable_files(self):
        with tempfile.TemporaryDirectory() as folder:
            pull_path = os.path.join(folder, "pull.json")
            checks_path = os.path.join(folder, "checks.json")
            with open(pull_path, "wb") as handle:
                handle.write(as_bytes(pull()))
            with open(checks_path, "wb") as handle:
                handle.write(as_bytes(BOTH))
            self.assert_answer(self.run_args(pull_path, checks_path), "READY")
            missing = os.path.join(folder, "no-such-file.json")
            argument_lists = {
                "no arguments": (),
                "one argument": (pull_path,),
                "three arguments": (pull_path, checks_path, checks_path),
                "pull file missing": (missing, checks_path),
                "checks file missing": (pull_path, missing),
            }
            for name, arguments in argument_lists.items():
                with self.subTest(case=name):
                    self.assert_bad_input(self.run_args(*arguments))
        latin_1 = json.dumps(pull(title="caf\u00e9"), ensure_ascii=False).encode("latin-1")
        contents = {
            "pull file not JSON": (b"not json", BOTH),
            "checks file not JSON": (pull(), b"not json"),
            "pull file not valid UTF-8": (latin_1, BOTH),
            "checks file empty": (pull(), b""),
            "pull file holds an array": ([pull()], BOTH),
            "checks file holds an array": (pull(), [run("tests"), run("review")]),
        }
        for name, (pull_content, checks_content) in contents.items():
            with self.subTest(case=name):
                self.assert_bad_input(self.run_files(pull_content, checks_content))

    def test_t14_invalid_pull_request(self):
        invalid = {
            "no state": pull_without("state"),
            "state OPEN": pull(state="OPEN"),
            "state a number": pull(state=1),
            "merged the text false": pull(merged="false"),
            "no merged": pull_without("merged"),
            "no draft": pull_without("draft"),
            "no head": pull_without("head"),
            "head a text string": pull(head=H),
            "head.sha of 39 characters": pull(sha=H[:39]),
            "head.sha in capital letters": pull(sha=H.upper()),
            "head.sha a number": pull(sha=1234567890123456789012345678901234567890),
        }
        for name, document in invalid.items():
            with self.subTest(case=name):
                self.assert_bad_input(self.run_files(document, BOTH))

    def test_t15_invalid_checks(self):
        both = [run("tests"), run("review")]
        invalid = {
            "no check_runs": checks_without("check_runs"),
            "check_runs an object": {"total_count": 0, "check_runs": {}},
            "an element that is a text string": checks(*both, "lint"),
            "an element with no name": checks(*both, run_without("name")),
            "id the text 5": checks(*both, run("lint", run_id="5")),
            "id true": checks(*both, run("lint", run_id=True)),
            "id 0": checks(*both, run("lint", run_id=0)),
            "status a number": checks(*both, run("lint", status=1)),
            "conclusion a number": checks(*both, run("lint", 1)),
            "an element with no head_sha": checks(*both, run_without("head_sha")),
            "no total_count": checks_without("total_count"),
            "total_count 3 with two elements": checks(*both, total_count=3),
            "total_count the text 2": checks(*both, total_count="2"),
        }
        for name, document in invalid.items():
            with self.subTest(case=name):
                self.assert_bad_input(self.run_files(pull(), document))

    def test_t16_validation_comes_before_the_result(self):
        merged = pull(state="closed", merged=True)
        self.assert_answer(self.run_files(merged, BOTH), "MERGED")
        self.assert_bad_input(self.run_files(merged, checks(run("tests", run_id=0))))
        self.assert_bad_input(self.run_files(merged, b"not json"))
        unreal = pull(state="closed", merged=True, sha="z" * 40)
        self.assert_bad_input(self.run_files(unreal, BOTH))

    @unittest.skipUnless(os.path.exists("/dev/full"), "needs /dev/full")
    def test_t17_standard_output_cannot_be_written(self):
        with open("/dev/full", "wb") as full:
            result = self.run_files(pull(), BOTH, stdout=full)
        self.assert_output_failed(result)


class TestRestOfSpecification(ProgramCase):
    def test_extra_first_rule_that_applies(self):
        failing = checks(run("tests", "failure"))
        cases = {
            "merged and still open": (pull(merged=True), failing, "MERGED"),
            "merged draft": (pull(state="closed", merged=True, draft=True), failing, "MERGED"),
            "closed draft": (pull(state="closed", draft=True), failing, "CLOSED"),
            "closed with failing checks": (pull(state="closed"), failing, "CLOSED"),
            "draft with failing checks": (pull(draft=True), failing, "DRAFT"),
            "draft with no checks": (pull(draft=True), checks(), "DRAFT"),
        }
        for name, (pull_content, checks_content, expected) in cases.items():
            with self.subTest(case=name):
                self.assert_answer(self.run_files(pull_content, checks_content), expected)

    def test_extra_validation_holds_for_closed_and_draft(self):
        broken = checks(run("lint", run_id=0))
        for name, document in (("closed", pull(state="closed")), ("draft", pull(draft=True))):
            with self.subTest(case=name):
                self.assert_bad_input(self.run_files(document, broken))
                self.assert_bad_input(self.run_files(document, {"total_count": 0}))

    def test_extra_other_invalid_pull_requests(self):
        arabic_indic_digits = "\u0663" * 40
        invalid = {
            "top level null": b"null",
            "top level a text string": b'"open"',
            "top level a number": b"7",
            "state null": pull(state=None),
            "state with a space": pull(state="open "),
            "state Closed": pull(state="Closed"),
            "state merged": pull(state="merged"),
            "state a list": pull(state=["open"]),
            "merged null": pull(merged=None),
            "merged 0": pull(merged=0),
            "merged 1": pull(merged=1),
            "draft null": pull(draft=None),
            "draft the text true": pull(draft="true"),
            "draft 0": pull(draft=0),
            "head null": pull(head=None),
            "head a list": pull(head=[H]),
            "head with no sha": pull(head={"ref": "req-7"}),
            "head.sha null": pull(sha=None),
            "head.sha empty": pull(sha=""),
            "head.sha of 41 characters": pull(sha=H + "0"),
            "head.sha with a letter g": pull(sha=H[:39] + "g"),
            "head.sha ending in a line feed": pull(sha=H[:39] + "\n"),
            "head.sha followed by a line feed": pull(sha=H + "\n"),
            "head.sha with a space": pull(sha=" " + H[:39]),
            "head.sha of other digits": pull(sha=arabic_indic_digits),
            "head.sha a list": pull(sha=[H]),
            "head.sha true": pull(sha=True),
        }
        for name, document in invalid.items():
            with self.subTest(case=name):
                self.assert_bad_input(self.run_files(document, BOTH))

    def test_extra_other_invalid_checks(self):
        both = [run("tests"), run("review")]
        invalid = {
            "top level null": b"null",
            "top level a text string": b'"check_runs"',
            "top level a number": b"0",
            "check_runs null": {"total_count": 0, "check_runs": None},
            "check_runs a text string": {"total_count": 0, "check_runs": ""},
            "total_count null": checks(*both, total_count=None),
            "total_count 2.0": checks(*both, total_count=2.0),
            "total_count true with one element": checks(run("tests"), total_count=True),
            "total_count false with no elements": checks(total_count=False),
            "total_count 1 with two elements": checks(*both, total_count=1),
            "total_count -2": checks(*both, total_count=-2),
            "total_count a list": checks(*both, total_count=[2]),
            "an element that is null": checks(*both, None),
            "an element that is a number": checks(*both, 5),
            "an element that is a list": checks(*both, [run("lint", run_id=5)]),
            "an element with no id": checks(*both, run_without("id")),
            "an element with no status": checks(*both, run_without("status")),
            "an element with no conclusion": checks(*both, run_without("conclusion")),
            "id false": checks(*both, run("lint", run_id=False)),
            "id -1": checks(*both, run("lint", run_id=-1)),
            "id 5.0": checks(*both, run("lint", run_id=5.0)),
            "id a list": checks(*both, run("lint", run_id=[5])),
            "name null": checks(*both, run(None, run_id=5)),
            "name a number": checks(*both, run(5, run_id=5)),
            "status null": checks(*both, run("lint", status=None)),
            "status true": checks(*both, run("lint", status=True)),
            "conclusion true": checks(*both, run("lint", True)),
            "conclusion a list": checks(*both, run("lint", ["success"])),
            "head_sha null": checks(*both, run("lint", sha=None)),
            "head_sha a number": checks(*both, run("lint", sha=5)),
        }
        for name, document in invalid.items():
            with self.subTest(case=name):
                self.assert_bad_input(self.run_files(pull(), document))

    def test_extra_id_null_is_invalid(self):
        document = {"total_count": 1, "check_runs": [run("lint", run_id=None)]}
        self.assert_bad_input(self.run_files(pull(), document))

    def test_extra_invalid_run_that_would_not_count_anyway(self):
        both = [run("tests"), run("review")]
        for position in (0, 1, 2):
            for name, element in (
                ("other name", run("lint", run_id=0)),
                ("other commit", run("review", sha=OTHER, run_id="9")),
                ("other commit, no conclusion", run_without("conclusion", name="tests")),
            ):
                with self.subTest(case=name, position=position):
                    runs = list(both)
                    runs.insert(position, element)
                    self.assert_bad_input(self.run_files(pull(), checks(*runs)))

    def test_extra_other_unreadable_or_malformed_files(self):
        pull_text = json.dumps(pull())
        cases = {
            "pull file empty": (b"", BOTH),
            "checks file not valid UTF-8": (pull(), b'{"total_count": 0, "check_runs": [], "x": "\xff"}'),
            "pull file is UTF-16": (pull_text.encode("utf-16"), BOTH),
            "pull file starts with a byte order mark": (b"\xef\xbb\xbf" + pull_text.encode("utf-8"), BOTH),
            "checks file starts with a byte order mark": (pull(), b"\xef\xbb\xbf" + as_bytes(BOTH)),
            "two objects one after another": ((pull_text + " " + pull_text).encode("utf-8"), BOTH),
            "text after the object": (pull(), as_bytes(BOTH) + b" x"),
            "object cut short": (pull_text[:-1].encode("utf-8"), BOTH),
            "NaN is not JSON": (pull(), b'{"total_count": 0, "check_runs": [], "score": NaN}'),
            "Infinity is not JSON": (pull(), b'{"total_count": 0, "check_runs": [], "score": -Infinity}'),
            "a repeated key is ambiguous": (
                b'{"state": "closed", "state": "open", "merged": false, "draft": false, '
                b'"head": {"sha": "' + H.encode("ascii") + b'"}}', BOTH),
            "a repeated key in the checks": (
                pull(), b'{"total_count": 0, "check_runs": [{}], "check_runs": []}'),
            "nesting too deep to read": (pull(), b"[" * 200000 + b"]" * 200000),
        }
        for name, (pull_content, checks_content) in cases.items():
            with self.subTest(case=name):
                self.assert_bad_input(self.run_files(pull_content, checks_content))

    def test_extra_directories_and_empty_names(self):
        with tempfile.TemporaryDirectory() as folder:
            pull_path = os.path.join(folder, "pull.json")
            checks_path = os.path.join(folder, "checks.json")
            with open(pull_path, "wb") as handle:
                handle.write(as_bytes(pull()))
            with open(checks_path, "wb") as handle:
                handle.write(as_bytes(BOTH))
            self.assert_bad_input(self.run_args(pull_path, folder))
            self.assert_bad_input(self.run_args(folder, checks_path))
            self.assert_bad_input(self.run_args(pull_path, ""))
            self.assert_bad_input(self.run_args("", checks_path))
            self.assert_bad_input(self.run_args(pull_path, pull_path))
            self.assert_bad_input(self.run_args(checks_path, checks_path))
            self.assert_bad_input(self.run_args(checks_path, pull_path))

    def test_extra_arguments_are_file_names_not_options(self):
        for arguments in (("--help",), ("-h", "--version"), ("--", "a", "b"), ("--help", "-v")):
            with self.subTest(arguments=arguments):
                self.assert_bad_input(self.run_args(*arguments))

    def test_extra_whitespace_and_non_ascii_content(self):
        document = pull(title="caf\u00e9 \u2603")
        raw = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        self.assertIn("caf\u00e9".encode("utf-8"), raw)
        named = checks(run("tests"), run("review"), run("pr\u00fcfung", "failure"))
        spaced = json.dumps(named, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        self.assert_answer(self.run_files(raw, spaced), "READY")
        escaped = json.dumps(document, ensure_ascii=True).encode("ascii")
        self.assert_answer(self.run_files(escaped, as_bytes(named)), "READY")

    def test_extra_only_the_named_keys_are_read(self):
        bare_pull = {"state": "open", "merged": False, "draft": False, "head": {"sha": H}}
        bare_checks = {
            "total_count": 2,
            "check_runs": [
                {"id": 1, "name": "tests", "status": "completed",
                 "conclusion": "success", "head_sha": H},
                {"id": 2, "name": "review", "status": "completed",
                 "conclusion": "success", "head_sha": H},
            ],
        }
        self.assert_answer(self.run_files(bare_pull, bare_checks), "READY")
        misleading = pull(
            mergeable=False,
            mergeable_state="dirty",
            merged_at="2026-01-01T00:00:00Z",
            closed_at="2026-01-01T00:00:00Z",
            locked=True,
            base={"ref": "main", "sha": H},
        )
        dressed = checks(
            run("tests", output={"title": "failure"}, check_suite={"id": 1}),
            run("review", app={"slug": "someone-else"}, pull_requests=[]),
        )
        self.assert_answer(self.run_files(misleading, dressed), "READY")

    def test_extra_status_and_conclusion_are_matched_exactly(self):
        cases = {
            "conclusion Success": (run("review", "Success"), "BLOCKED review"),
            "conclusion with a space": (run("review", "success "), "BLOCKED review"),
            "conclusion empty": (run("review", ""), "BLOCKED review"),
            "conclusion failure": (run("review", "failure"), "BLOCKED review"),
            "status Completed": (run("review", "success", "Completed"), "WAITING"),
            "status with a space": (run("review", "success", "completed "), "WAITING"),
            "status empty": (run("review", "success", ""), "WAITING"),
            "status waiting": (run("review", None, "waiting"), "WAITING"),
            "status requested": (run("review", None, "requested"), "WAITING"),
            "status pending": (run("review", None, "pending"), "WAITING"),
            "queued with a failure conclusion": (run("review", "failure", "queued"), "WAITING"),
        }
        for name, (review, expected) in cases.items():
            with self.subTest(case=name):
                document = checks(run("tests"), review)
                self.assert_answer(self.run_files(pull(), document), expected)

    def test_extra_waiting_and_blocked_combinations(self):
        cases = {
            "both in progress": (
                checks(run("tests", None, "in_progress"), run("review", None, "queued")),
                "WAITING"),
            "tests in progress, review success": (
                checks(run("tests", None, "in_progress"), run("review")), "WAITING"),
            "tests in progress, review failure": (
                checks(run("tests", None, "in_progress"), run("review", "failure")),
                "BLOCKED review"),
            "only review, failure": (checks(run("review", "failure")), "BLOCKED review"),
            "only tests, failure": (checks(run("tests", "failure")), "BLOCKED tests"),
            "only review, success": (checks(run("review")), "WAITING"),
            "only other names": (checks(run("lint"), run("build", "failure")), "WAITING"),
            "failures only on another commit": (
                checks(run("tests", "failure", sha=OTHER), run("review", "failure", sha=OTHER)),
                "WAITING"),
            "tests on H, review only on another commit": (
                checks(run("tests"), run("review", sha=OTHER)), "WAITING"),
            "tests failure on H, review only on another commit": (
                checks(run("tests", "failure"), run("review", sha=OTHER)), "BLOCKED tests"),
            "commit in capital letters is another commit": (
                checks(run("tests", sha=H.upper()), run("review", sha=H.upper())), "WAITING"),
            "commit with a trailing space is another commit": (
                checks(run("tests"), run("review", sha=H + " ")), "WAITING"),
            "abbreviated commit is another commit": (
                checks(run("tests"), run("review", sha=H[:7])), "WAITING"),
        }
        for name, (document, expected) in cases.items():
            with self.subTest(case=name):
                self.assert_answer(self.run_files(pull(), document), expected)

    def test_extra_a_re_run_replaces_the_earlier_run(self):
        tests = run("tests", run_id=1)
        cases = {
            "failure, then re-run in progress": (
                [run("review", "failure", run_id=10),
                 run("review", None, "in_progress", run_id=11)], "WAITING"),
            "success, then re-run queued": (
                [run("review", run_id=10), run("review", None, "queued", run_id=11)],
                "WAITING"),
            "in progress, then success": (
                [run("review", None, "in_progress", run_id=10), run("review", run_id=11)],
                "READY"),
            "three runs, the middle id fails": (
                [run("review", run_id=10), run("review", "failure", run_id=11),
                 run("review", run_id=12)], "READY"),
            "three runs, the highest id fails": (
                [run("review", "failure", run_id=12), run("review", run_id=10),
                 run("review", run_id=11)], "BLOCKED review"),
            "a higher id on another commit does not count": (
                [run("review", run_id=10), run("review", "failure", sha=OTHER, run_id=11)],
                "READY"),
            "a higher id under another name does not count": (
                [run("review", run_id=10), run("Review", "failure", run_id=11)], "READY"),
            "ids are compared as numbers, not text": (
                [run("review", "failure", run_id=9), run("review", run_id=10)], "READY"),
        }
        for name, (reviews, expected) in cases.items():
            for order in ("as listed", "reversed"):
                with self.subTest(case=name, order=order):
                    runs = [tests] + reviews
                    if order == "reversed":
                        runs.reverse()
                    self.assert_answer(self.run_files(pull(), checks(*runs)), expected)
        both_re_run = checks(
            run("tests", "failure", run_id=1), run("review", "failure", run_id=2),
            run("tests", run_id=3), run("review", run_id=4),
        )
        self.assert_answer(self.run_files(pull(), both_re_run), "READY")

    def test_extra_equal_ids_never_depend_on_the_order(self):
        tests = run("tests", run_id=1)
        cases = {
            "success and failure": (run("review"), run("review", "failure"), "BLOCKED review"),
            "success and in progress": (
                run("review"), run("review", None, "in_progress"), "WAITING"),
            "failure and in progress": (
                run("review", "failure"), run("review", None, "in_progress"),
                "BLOCKED review"),
            "success twice": (run("review"), run("review"), "READY"),
        }
        for name, (first, second, expected) in cases.items():
            first = dict(first, id=10)
            second = dict(second, id=10)
            for order, runs in (("a", (tests, first, second)), ("b", (second, first, tests))):
                with self.subTest(case=name, order=order):
                    self.assert_answer(self.run_files(pull(), checks(*runs)), expected)

    def test_extra_id_has_no_upper_bound(self):
        digits = "9" * 5000
        earlier = run("review", "failure", run_id=7)
        later = run("review", run_id=8)
        document = json.dumps(checks(run("tests", run_id=1), later, earlier))
        document = document.replace('"id": 8,', '"id": %s,' % digits)
        self.assertIn(digits, document)
        self.assert_answer(self.run_files(pull(), document.encode("ascii")), "READY")
        large = 12345678901234567890
        document = checks(run("tests"), run("review", "failure", run_id=large),
                          run("review", run_id=large - 1))
        self.assert_answer(self.run_files(pull(), document), "BLOCKED review")

    def test_extra_many_check_runs(self):
        runs = [run("lint", "failure", run_id=number) for number in range(1, 301)]
        runs.insert(100, run("tests", run_id=500))
        runs.insert(200, run("review", run_id=501))
        self.assert_answer(self.run_files(pull(), checks(*runs)), "READY")

    def test_extra_no_text_from_a_file_is_printed(self):
        marker = "ZEBRA-MARKER"
        named = pull(title=marker, body=marker, user={"login": marker})
        named["head"]["ref"] = marker
        document = checks(
            run("tests", output={"title": marker}),
            run("review", "failure", details_url=marker),
            run(marker, "failure"),
        )
        result = self.run_files(named, document)
        self.assert_answer(result, "BLOCKED review")
        self.assertNotIn(marker.encode("ascii"), result.stdout)
        bad_inputs = (
            (pull(state=marker, title=marker), BOTH),
            (pull(sha=marker), BOTH),
            (named, checks(run(marker, status=5))),
            (named, checks(run("tests", marker, run_id=marker))),
            (named, checks(total_count=marker)),
            ((json.dumps(named) + marker).encode("utf-8"), BOTH),
            (named, marker.encode("ascii")),
        )
        for pull_content, checks_content in bad_inputs:
            result = self.run_files(pull_content, checks_content)
            self.assert_bad_input(result)
            self.assertNotIn(marker.encode("ascii"), result.stderr)

    def test_extra_file_names_are_not_printed(self):
        with tempfile.TemporaryDirectory() as folder:
            pull_path = os.path.join(folder, "ZEBRA-PULL.json")
            checks_path = os.path.join(folder, "ZEBRA-CHECKS.json")
            for arguments in ((pull_path, checks_path), (pull_path,), ("ZEBRA-ONLY",)):
                with self.subTest(arguments=len(arguments)):
                    result = self.run_args(*arguments)
                    self.assert_bad_input(result)
                    self.assertNotIn(b"ZEBRA", result.stderr)

    @unittest.skipUnless(os.name == "posix", "an empty environment is a POSIX case")
    def test_extra_runs_with_an_empty_environment(self):
        self.assert_answer(self.run_files(pull(), BOTH, env={}), "READY")
        self.assert_bad_input(self.run_files(b"{", BOTH, env={}))

    @unittest.skipUnless(os.name == "posix", "a pipe with no reader is a POSIX case")
    def test_extra_reader_gone(self):
        read_end, write_end = os.pipe()
        os.close(read_end)
        try:
            result = self.run_files(pull(), BOTH, stdout=write_end)
        finally:
            os.close(write_end)
        self.assert_output_failed(result)

    @unittest.skipUnless(os.path.exists("/dev/full"), "needs /dev/full")
    def test_extra_bad_input_is_reported_whatever_standard_output_is(self):
        with open("/dev/full", "wb") as full:
            result = self.run_files(pull(state="OPEN"), BOTH, stdout=full)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith(ERROR_PREFIX), result.stderr)
        self.assertEqual(result.stderr.count(b"\n"), 1, result.stderr)

    def test_extra_writes_no_file(self):
        with tempfile.TemporaryDirectory() as folder:
            pull_path = os.path.join(folder, "pull.json")
            checks_path = os.path.join(folder, "checks.json")
            with open(pull_path, "wb") as handle:
                handle.write(as_bytes(pull()))
            with open(checks_path, "wb") as handle:
                handle.write(as_bytes(BOTH))
            result = subprocess.run(
                [sys.executable, "-B", PROGRAM, pull_path, checks_path],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                cwd=folder,
            )
            self.assert_answer(result, "READY")
            self.assertEqual(sorted(os.listdir(folder)), ["checks.json", "pull.json"])
            with open(pull_path, "rb") as handle:
                self.assertEqual(handle.read(), as_bytes(pull()))
            with open(checks_path, "rb") as handle:
                self.assertEqual(handle.read(), as_bytes(BOTH))

    def test_extra_program_imports_only_what_it_needs(self):
        with open(PROGRAM, "rb") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)
        self.assertLessEqual(imported, {"json", "os", "sys"})
        forbidden = {"environ", "environb", "getenv", "system", "popen", "fork",
                     "exec", "eval", "__import__", "input", "print", "socket",
                     "subprocess", "urllib", "remove", "unlink", "rename"}
        self.assertEqual(names & forbidden, set())

    def test_extra_the_required_checks_are_fixed_in_the_code(self):
        with open(PROGRAM, "rb") as handle:
            tree = ast.parse(handle.read())
        texts = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        self.assertIn("tests", texts)
        self.assertIn("review", texts)


if __name__ == "__main__":
    unittest.main()
