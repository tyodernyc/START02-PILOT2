"""Tests for attention.py (build request #38).

Every check V1 to V10 of the request has one test method named after it.
Each case runs the program as a separate process and compares standard
output, standard error and the exit status exactly. The tests named
test_extra_* cover the rest of the specification (S1 to S7).
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "attention.py")
ERROR_PREFIX = b"attention: "

H = "0123456789abcdef0123456789abcdef01234567"
H2 = "fedcba9876543210fedcba9876543210fedcba98"
H3 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def pull(number=5, sha=H, draft=False, ref=None):
    return {
        "number": number,
        "draft": draft,
        "head": {"ref": ref or "req-%d" % number, "sha": sha},
    }


def issue(number, title="Build request: x", **extra):
    item = {"number": number, "title": title}
    item.update(extra)
    return item


def run(run_id, name, status="completed", conclusion="success"):
    return {"id": run_id, "name": name, "status": status, "conclusion": conclusion}


def runs(*items):
    return {"check_runs": list(items)}


def good_runs(base=1):
    return runs(run(base, "tests"), run(base + 1, "review"))


def comment(comment_id, login, body):
    return {"id": comment_id, "user": {"login": login}, "body": body}


def review(sha=H, leftovers=("one", "two"), comment_id=1):
    lines = ["BLOCKING:", "- none", "", "LEFTOVER:"]
    lines.extend("- " + item for item in leftovers)
    lines.extend(["", "HEAD: " + sha, "VERDICT: PASS"])
    return comment(comment_id, "claude[bot]", "\n".join(lines))


def snapshot(**parts):
    data = {"issues": [], "pulls": [], "check_runs": {}, "comments": {}}
    data.update(parts)
    return data


class Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name

    def run_program(self, *args, **kwargs):
        return subprocess.run(
            [sys.executable, PROGRAM] + list(args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=kwargs.get("cwd", self.folder),
        )

    def write(self, content, name="snapshot.json"):
        path = os.path.join(self.folder, name)
        if not isinstance(content, bytes):
            content = json.dumps(content).encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def ok(self, data, expected_lines):
        result = self.run_program(self.write(data))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout, "".join(line + "\n" for line in expected_lines).encode("utf-8"))
        self.assertEqual(result.returncode, 0)

    def bad(self, *args):
        result = self.run_program(*args)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith(ERROR_PREFIX), result.stderr)
        self.assertEqual(result.stderr.count(b"\n"), 1)
        self.assertTrue(result.stderr.endswith(b"\n"))
        self.assertNotIn(b"Traceback", result.stderr)

    def bad_snapshot(self, data):
        self.bad(self.write(data))


class TestChecks(Case):
    def test_v1_empty_snapshot(self):
        self.ok(snapshot(), ["NOTHING WAITING"])

    def test_v2_merge_wanted_with_two_leftovers(self):
        data = snapshot(
            pulls=[pull()],
            check_runs={H: good_runs()},
            comments={"5": [review()]},
        )
        self.ok(data, ["MERGE WANTED: pull request 5 (leftovers: 2)"])

    def test_v3_leftovers_unknown_and_zero(self):
        other = snapshot(
            pulls=[pull()],
            check_runs={H: good_runs()},
            comments={"5": [review(sha=H2)]},
        )
        self.ok(other, ["MERGE WANTED: pull request 5 (leftovers: unknown)"])
        none = snapshot(
            pulls=[pull()],
            check_runs={H: good_runs()},
            comments={"5": [review(leftovers=("none",))]},
        )
        self.ok(none, ["MERGE WANTED: pull request 5 (leftovers: 0)"])

    def test_v4_highest_run_id_counts(self):
        passing = snapshot(
            pulls=[pull()],
            check_runs={
                H: runs(
                    run(10, "tests", conclusion="failure"),
                    run(11, "tests"),
                    run(12, "review"),
                )
            },
        )
        self.ok(passing, ["MERGE WANTED: pull request 5 (leftovers: unknown)"])
        failing = snapshot(
            pulls=[pull()],
            check_runs={
                H: runs(
                    run(10, "tests"),
                    run(11, "tests", conclusion="failure"),
                    run(12, "review"),
                )
            },
        )
        self.ok(failing, ["FAILED: pull request 5 (tests)"])

    def test_v5_waiting_and_drafts(self):
        pending = snapshot(
            pulls=[pull()],
            check_runs={
                H: runs(run(1, "tests"), run(2, "review", status="in_progress", conclusion=None))
            },
        )
        self.ok(pending, ["WAITING: pull request 5"])
        self.ok(snapshot(pulls=[pull()]), ["WAITING: pull request 5"])
        draft = snapshot(pulls=[pull(draft=True)], check_runs={H: good_runs()})
        self.ok(draft, ["NOTHING WAITING"])

    def test_v6_build_requests(self):
        self.ok(
            snapshot(issues=[issue(7)], comments={"7": [comment(1, "claude", "stopped")]}),
            ["DECISION WANTED: issue 7"],
        )
        self.ok(snapshot(issues=[issue(7)]), ["QUEUED: issue 7"])
        self.ok(
            snapshot(issues=[issue(7)], comments={"7": [comment(1, "tyodernyc", "go on")]}),
            ["NOTHING WAITING"],
        )
        self.ok(
            snapshot(
                issues=[issue(7)],
                pulls=[pull(number=9, ref="req-7")],
                check_runs={H: good_runs()},
            ),
            ["MERGE WANTED: pull request 9 (leftovers: unknown)"],
        )

    def test_v7_other_issues_and_pull_request_items_ignored(self):
        data = snapshot(
            issues=[
                issue(3, title="A plain issue"),
                issue(4, pull_request={"url": "x"}),
                {"pull_request": {}},
            ]
        )
        self.ok(data, ["NOTHING WAITING"])

    def test_v8_every_group_in_order(self):
        h4 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        h5 = "cccccccccccccccccccccccccccccccccccccccc"
        h6 = "dddddddddddddddddddddddddddddddddddddddd"
        data = snapshot(
            issues=[
                issue(30),
                issue(12),
                issue(25),
                issue(11),
                issue(40, title="not a build request"),
            ],
            pulls=[
                pull(number=21, sha=H),
                pull(number=8, sha=H2),
                pull(number=15, sha=H3),
                pull(number=9, sha=h4),
                pull(number=3, sha=h5),
                pull(number=14, sha=h6),
            ],
            check_runs={
                H: good_runs(),
                H2: good_runs(),
                H3: runs(run(1, "tests", conclusion="failure"), run(2, "review", conclusion="cancelled")),
                h4: runs(run(1, "tests", conclusion="timed_out"), run(2, "review")),
                h5: runs(run(1, "tests")),
                h6: runs(),
            },
            comments={
                "8": [review(sha=H2, leftovers=("a",))],
                "21": [review(leftovers=())],
                "12": [comment(5, "tyodernyc", "x"), comment(6, "claude", "stopped")],
                "25": [comment(3, "claude", "stopped"), comment(4, "tyodernyc", "x")],
            },
        )
        self.ok(
            data,
            [
                "MERGE WANTED: pull request 8 (leftovers: 1)",
                "MERGE WANTED: pull request 21 (leftovers: 0)",
                "DECISION WANTED: issue 12",
                "FAILED: pull request 9 (tests)",
                "FAILED: pull request 15 (tests, review)",
                "WAITING: pull request 3",
                "WAITING: pull request 14",
                "QUEUED: issue 11",
                "QUEUED: issue 30",
            ],
        )

    def test_v9_required_checks_given(self):
        data = snapshot(
            pulls=[pull()],
            check_runs={H: runs(run(1, "ci", conclusion="failure"), run(2, "review"))},
            required_checks=["ci", "review"],
        )
        self.ok(data, ["FAILED: pull request 5 (ci)"])

    def test_v10_bad_input(self):
        path = self.write(snapshot())
        self.bad()
        self.bad(path, path)
        self.bad(os.path.join(self.folder, "missing.json"))
        self.bad(self.write(b"this is not json", "text.json"))
        self.bad_snapshot(snapshot(pulls=[pull(sha=H[:39])]))
        self.bad_snapshot(snapshot(issues=[issue(True)]))


class TestExtra(Case):
    def test_extra_default_required_checks_are_tests_and_review(self):
        data = snapshot(
            pulls=[pull()],
            check_runs={H: runs(run(1, "ci"), run(2, "other"))},
        )
        self.ok(data, ["WAITING: pull request 5"])

    def test_extra_failed_names_follow_required_checks_order(self):
        data = snapshot(
            pulls=[pull()],
            check_runs={
                H: runs(
                    run(1, "a", conclusion="failure"),
                    run(2, "b", conclusion="failure"),
                    run(3, "c"),
                )
            },
            required_checks=["c", "b", "a"],
        )
        self.ok(data, ["FAILED: pull request 5 (b, a)"])

    def test_extra_failure_beats_waiting(self):
        data = snapshot(
            pulls=[pull()],
            check_runs={H: runs(run(1, "tests", conclusion="failure"))},
        )
        self.ok(data, ["FAILED: pull request 5 (tests)"])

    def test_extra_completed_without_conclusion_is_failed(self):
        data = snapshot(
            pulls=[pull()],
            check_runs={H: runs(run(1, "tests", conclusion=None), run(2, "review"))},
        )
        self.ok(data, ["FAILED: pull request 5 (tests)"])

    def test_extra_run_name_must_match_exactly(self):
        data = snapshot(
            pulls=[pull()],
            check_runs={H: runs(run(1, "Tests"), run(2, "tests "), run(3, "review"))},
        )
        self.ok(data, ["WAITING: pull request 5"])

    def test_extra_highest_review_id_wins(self):
        data = snapshot(
            pulls=[pull()],
            check_runs={H: good_runs()},
            comments={
                "5": [
                    review(leftovers=("a", "b", "c"), comment_id=9),
                    review(leftovers=("a",), comment_id=4),
                ]
            },
        )
        self.ok(data, ["MERGE WANTED: pull request 5 (leftovers: 3)"])

    def test_extra_review_must_come_from_the_reviewer_bot(self):
        data = snapshot(
            pulls=[pull()],
            check_runs={H: good_runs()},
            comments={"5": [comment(1, "claude[bot]x", review()["body"]), comment(2, "tyodernyc", review()["body"])]},
        )
        self.ok(data, ["MERGE WANTED: pull request 5 (leftovers: unknown)"])

    def test_extra_review_without_leftover_heading_is_unknown(self):
        body = "BLOCKING:\n- none\nHEAD: " + H + "\nVERDICT: PASS"
        data = snapshot(
            pulls=[pull()],
            check_runs={H: good_runs()},
            comments={"5": [comment(1, "claude[bot]", body)]},
        )
        self.ok(data, ["MERGE WANTED: pull request 5 (leftovers: unknown)"])

    def test_extra_leftover_section_ends_at_next_heading(self):
        body = "\n".join(
            ["LEFTOVER:", "- a", "- b: with colon", "NOTES:", "- not counted", "HEAD: " + H]
        )
        data = snapshot(
            pulls=[pull()],
            check_runs={H: good_runs()},
            comments={"5": [comment(1, "claude[bot]", body)]},
        )
        self.ok(data, ["MERGE WANTED: pull request 5 (leftovers: 2)"])

    def test_extra_leftover_section_runs_to_end_and_handles_crlf(self):
        body = "HEAD: " + H + "\r\nLEFTOVER:\r\n- a\r\n- none\r\n\r\n- b\r\n"
        data = snapshot(
            pulls=[pull()],
            check_runs={H: good_runs()},
            comments={"5": [comment(1, "claude[bot]", body)]},
        )
        self.ok(data, ["MERGE WANTED: pull request 5 (leftovers: 2)"])

    def test_extra_head_line_must_be_exact(self):
        for line in ("HEAD:  " + H, "head: " + H, "HEAD: " + H + " ", "xHEAD: " + H):
            data = snapshot(
                pulls=[pull()],
                check_runs={H: good_runs()},
                comments={"5": [comment(1, "claude[bot]", "LEFTOVER:\n- a\n" + line)]},
            )
            self.ok(data, ["MERGE WANTED: pull request 5 (leftovers: unknown)"])

    def test_extra_build_request_title_prefix_is_exact(self):
        data = snapshot(
            issues=[
                issue(1, title="build request: x"),
                issue(2, title=" Build request: x"),
                issue(3, title="Build request:"),
                issue(4, title="Build request x"),
            ]
        )
        self.ok(data, ["QUEUED: issue 3"])

    def test_extra_req_branch_must_equal_exactly(self):
        data = snapshot(
            issues=[issue(7)],
            pulls=[pull(number=9, ref="req-70"), pull(number=10, ref="req-7x")],
        )
        self.ok(
            data,
            ["WAITING: pull request 9", "WAITING: pull request 10", "QUEUED: issue 7"],
        )

    def test_extra_draft_pull_request_still_takes_the_request(self):
        data = snapshot(issues=[issue(7)], pulls=[pull(number=9, ref="req-7", draft=True)])
        self.ok(data, ["NOTHING WAITING"])

    def test_extra_highest_comment_id_decides_the_last_comment(self):
        data = snapshot(
            issues=[issue(7)],
            comments={"7": [comment(8, "tyodernyc", "later"), comment(2, "claude", "earlier")]},
        )
        self.ok(data, ["NOTHING WAITING"])

    def test_extra_extra_keys_and_fields_are_ignored(self):
        item = pull()
        item["head"]["extra"] = [1, 2]
        item["extra"] = {"a": None}
        data = snapshot(pulls=[item], extra_key=[1, 2, 3])
        self.ok(data, ["WAITING: pull request 5"])

    def test_extra_unicode_in_titles_and_comments_is_fine(self):
        data = snapshot(
            issues=[issue(7, title="Build request: café ☃")],
            comments={"7": [comment(1, "claude", "éè")]},
        )
        self.ok(data, ["DECISION WANTED: issue 7"])

    def test_extra_unicode_check_name_is_written_as_utf8(self):
        data = snapshot(
            pulls=[pull()],
            check_runs={H: runs(run(1, "tést", conclusion="failure"))},
            required_checks=["tést"],
        )
        self.ok(data, ["FAILED: pull request 5 (tést)"])

    def test_extra_only_check_names_are_echoed(self):
        secret = "SECRET-TITLE-TEXT"
        data = snapshot(
            issues=[issue(7, title="Build request: " + secret)],
            pulls=[pull(number=9, ref="x")],
            check_runs={H: runs(run(1, secret, conclusion="failure"))},
        )
        result = self.run_program(self.write(data))
        self.assertNotIn(secret.encode(), result.stdout + result.stderr)
        self.assertEqual(result.stdout, b"WAITING: pull request 9\nQUEUED: issue 7\n")

    def test_extra_bad_structures_exit_2(self):
        pulls_ok = [pull()]
        cases = [
            [],
            "text",
            None,
            {"issues": [], "pulls": [], "check_runs": {}},
            {"issues": [], "pulls": [], "comments": {}},
            snapshot(issues={}),
            snapshot(issues=[5]),
            snapshot(issues=[{"number": 1}]),
            snapshot(issues=[{"title": "Build request: x"}]),
            snapshot(issues=[issue("7")]),
            snapshot(issues=[issue(1.5)]),
            snapshot(issues=[issue(1, title=None)]),
            snapshot(pulls={}),
            snapshot(pulls=[5]),
            snapshot(pulls=[dict(pull(), number=False)]),
            snapshot(pulls=[dict(pull(), draft=0)]),
            snapshot(pulls=[dict(pull(), draft="false")]),
            snapshot(pulls=[dict(pull(), head=None)]),
            snapshot(pulls=[dict(pull(), head={"sha": H})]),
            snapshot(pulls=[dict(pull(), head={"ref": 1, "sha": H})]),
            snapshot(pulls=[pull(sha=H.upper())]),
            snapshot(pulls=[pull(sha=H + "0")]),
            snapshot(pulls=[pull(sha="g" * 40)]),
            snapshot(pulls=[pull(sha=H + "\n")]),
            snapshot(pulls=pulls_ok, check_runs=[]),
            snapshot(pulls=pulls_ok, check_runs={H: []}),
            snapshot(pulls=pulls_ok, check_runs={H: {}}),
            snapshot(pulls=pulls_ok, check_runs={H: {"check_runs": {}}}),
            snapshot(pulls=pulls_ok, check_runs={H: runs(5)}),
            snapshot(pulls=pulls_ok, check_runs={H: runs(run(True, "tests"))}),
            snapshot(pulls=pulls_ok, check_runs={H: runs(run("1", "tests"))}),
            snapshot(pulls=pulls_ok, check_runs={H: runs(run(1, 5))}),
            snapshot(pulls=pulls_ok, check_runs={H: runs(run(1, "tests", status=None))}),
            snapshot(pulls=pulls_ok, check_runs={H: runs(run(1, "tests", conclusion=5))}),
            snapshot(pulls=pulls_ok, check_runs={H: runs({"id": 1, "name": "tests", "status": "completed"})}),
            snapshot(comments=[]),
            snapshot(comments={"5": {}}),
            snapshot(comments={"5": [5]}),
            snapshot(comments={"5": [comment(True, "a", "b")]}),
            snapshot(comments={"5": [{"id": 1, "user": None, "body": "b"}]}),
            snapshot(comments={"5": [{"id": 1, "user": {"login": 1}, "body": "b"}]}),
            snapshot(comments={"5": [{"id": 1, "user": {"login": "a"}, "body": None}]}),
            snapshot(comments={"5": [{"id": 1, "user": {"login": "a"}}]}),
            snapshot(required_checks=[]),
            snapshot(required_checks="tests"),
            snapshot(required_checks=None),
            snapshot(required_checks=["a", "a"]),
            snapshot(required_checks=["a", ""]),
            snapshot(required_checks=["a", 1]),
        ]
        for data in cases:
            with self.subTest(data=data):
                self.bad_snapshot(data)

    def test_extra_pull_request_items_in_issues_are_not_validated(self):
        data = snapshot(issues=[{"pull_request": {}, "number": "x"}])
        self.ok(data, ["NOTHING WAITING"])

    def test_extra_bad_files_exit_2(self):
        cases = [
            b"",
            b"{",
            b"\xff\xfe{}",
            b"\xef\xbb\xbf{}",
            b"{\"issues\": [], \"pulls\": [], \"check_runs\": {}, \"comments\": {}} x",
            b"[" * 100000,
            b"{\"a\": " + b"9" * 6000 + b"}",
        ]
        for content in cases:
            with self.subTest(content=content[:30]):
                self.bad(self.write(content))

    def test_extra_directory_is_unreadable(self):
        self.bad(self.folder)

    def test_extra_empty_argument_exits_2(self):
        self.bad("")

    def test_extra_error_never_echoes_input(self):
        name = "SECRET-NAME"
        result = self.run_program(os.path.join(self.folder, name))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(name.encode(), result.stderr)
        data = snapshot(issues=[issue(1, title=name)], pulls=[dict(pull(), draft=name)])
        result = self.run_program(self.write(data))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(name.encode(), result.stderr)

    def test_extra_unwritable_stdout_exits_1(self):
        path = self.write(snapshot())
        result = subprocess.run(
            [sys.executable, PROGRAM, path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=self.folder,
        )
        self.assertEqual(result.returncode, 0)
        if os.path.exists("/dev/full"):
            with open("/dev/full", "wb") as full:
                result = subprocess.run(
                    [sys.executable, PROGRAM, path],
                    stdin=subprocess.DEVNULL,
                    stdout=full,
                    stderr=subprocess.PIPE,
                    cwd=self.folder,
                )
            self.assertEqual(result.returncode, 1)
            self.assertTrue(result.stderr.startswith(ERROR_PREFIX), result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)

    def test_extra_closed_stdout_exits_1(self):
        path = self.write(snapshot())
        result = subprocess.run(
            [sys.executable, "-c",
             "import os, sys\nos.close(1)\nsys.argv = ['attention.py', sys.argv[1]]\n"
             "import runpy\nrunpy.run_path(%r, run_name='__main__')" % PROGRAM,
             path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.folder,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_extra_unencodable_check_name_exits_1(self):
        data = (
            b'{"issues": [], "pulls": [{"number": 5, "draft": false, "head": {"ref": "r", "sha": "'
            + H.encode()
            + b'"}}], "check_runs": {"' + H.encode()
            + b'": {"check_runs": [{"id": 1, "name": "\\ud800", "status": "completed",'
            b' "conclusion": "failure"}]}}, "comments": {}, "required_checks": ["\\ud800"]}'
        )
        result = self.run_program(self.write(data))
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.startswith(ERROR_PREFIX), result.stderr)

    def test_extra_working_directory_does_not_matter(self):
        path = self.write(snapshot())
        result = self.run_program(path, cwd=os.path.dirname(self.folder))
        self.assertEqual(result.stdout, b"NOTHING WAITING\n")

    def test_extra_source_is_python_3_8_compatible(self):
        with open(PROGRAM, "rb") as handle:
            source = handle.read()
        ast.parse(source, feature_version=(3, 8))
        text = source.decode("utf-8")
        for banned in ("removeprefix", "removesuffix", "match ", "zip(strict"):
            self.assertNotIn(banned, text)

    def test_extra_program_opens_one_file_and_no_network(self):
        with open(PROGRAM, "rb") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"json", "os", "re", "sys"})
        opens = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
        ]
        self.assertEqual(len(opens), 1)



def with_extra(data, raw_value):
    """The JSON text of data with an extra ignored field holding raw_value."""
    return (json.dumps(data)[:-1] + ',"extra":' + raw_value + "}").encode("utf-8")


class TestHardening(Case):
    """Build request #44: F1 (non-JSON constants), F2 (large integers) and
    F3 (unwritable standard error or output)."""

    def test_f1_non_json_constants_are_bad_input(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                self.bad(self.write(with_extra(snapshot(), constant)))

    def test_f1_constant_inside_a_nested_ignored_field(self):
        raw = json.dumps(snapshot())[:-1] + ',"extra":{"a":[1,{"b":NaN}]}}'
        self.bad(self.write(raw.encode("utf-8")))

    def test_f1_constant_in_a_used_field(self):
        raw = (
            '{"issues":[],"pulls":[],"check_runs":{},"comments":{},'
            '"required_checks":[NaN]}'
        )
        self.bad(self.write(raw.encode("utf-8")))

    def test_f1_names_that_merely_look_like_constants_are_text(self):
        data = snapshot(extra=["NaN", "Infinity", "-Infinity"])
        self.ok(data, ["NOTHING WAITING"])

    def test_f2_five_thousand_digit_integer_in_an_ignored_field(self):
        digits = "1" + "0" * 4999
        self.assertEqual(len(digits), 5000)
        for raw in (digits, "-" + digits):
            with self.subTest(raw=raw[:3]):
                data = snapshot(
                    issues=[issue(7)],
                    pulls=[pull(5)],
                    check_runs={H: good_runs()},
                )
                result = self.run_program(self.write(with_extra(data, raw)))
                plain = self.run_program(self.write(data))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, b"")
                self.assertEqual(result.stdout, plain.stdout)
                self.assertEqual(plain.returncode, 0)
                self.assertNotEqual(result.stdout, b"")

    def test_f3_unwritable_standard_error_still_gives_status_2(self):
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full not available")
        with open("/dev/full", "wb") as full:
            result = subprocess.run(
                [sys.executable, PROGRAM],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=full,
                cwd=self.folder,
            )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")

    def test_f3_unwritable_standard_error_with_bad_snapshot(self):
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full not available")
        path = self.write(with_extra(snapshot(), "NaN"))
        with open("/dev/full", "wb") as full:
            result = subprocess.run(
                [sys.executable, PROGRAM, path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=full,
                cwd=self.folder,
            )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")

    def test_f3_unwritable_standard_output_gives_status_1(self):
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full not available")
        path = self.write(snapshot())
        with open("/dev/full", "wb") as full:
            result = subprocess.run(
                [sys.executable, PROGRAM, path],
                stdin=subprocess.DEVNULL,
                stdout=full,
                stderr=subprocess.PIPE,
                cwd=self.folder,
            )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b"Traceback", result.stderr)
        self.assertEqual(result.stderr.count(b"\n"), 1)
        self.assertTrue(result.stderr.startswith(ERROR_PREFIX))


if __name__ == "__main__":
    unittest.main()
