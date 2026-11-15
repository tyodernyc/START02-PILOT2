"""Tests for merge_check.py (build request #46).

Every check V1 to V12 of build request #46 has at least one test method
named after it, and every amendment A1 to A5 of build request #48 has tests
in TestAmendments, and every change H1 to H5 of build request #50 has tests
in TestHardening. Each case runs the program as a separate process and compares
standard output, standard error and the exit status exactly. The tests named
test_extra_* cover the rest of the specification (S1 to S5).
"""

import ast
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "merge_check.py")
ERROR_PREFIX = b"merge_check: "

H = "0123456789abcdef0123456789abcdef01234567"
H2 = "fedcba9876543210fedcba9876543210fedcba98"

CLAUDE = "claude[bot]"
CODEX = "chatgpt-codex-connector[bot]"


def run(run_id, name, status="completed", conclusion="success"):
    return {"id": run_id, "name": name, "status": status, "conclusion": conclusion}


def comment(comment_id, login, body):
    return {"id": comment_id, "user": {"login": login}, "body": body}


def claude_review(sha=H, verdict="PASS", comment_id=1):
    body = "## Automatic review\nHEAD: %s\nVERDICT: %s\nBLOCKING:\n- none" % (sha, verdict)
    return comment(comment_id, CLAUDE, body)


def codex_review(sha=H[:10], comment_id=2, verdict="Didn't find any major issues"):
    body = "Codex Review: %s.\n\nReviewed commit: `%s`" % (verdict, sha)
    return comment(comment_id, CODEX, body)


def review_comment(comment_id, body, commit_id=H, login=CODEX):
    item = comment(comment_id, login, body)
    item["commit_id"] = commit_id
    return item


def snapshot(**parts):
    """A snapshot in which every rule passes; keyword arguments replace parts."""
    data = {
        "pull": {
            "number": 7,
            "state": "open",
            "draft": False,
            "head": {"sha": H},
            "body": "## Summary\nOne thing.\n\n## Open questions\nnone\n",
        },
        "files": [{"filename": "merge_check.py"}, {"filename": "test_merge_check.py"}],
        "check_runs": {"check_runs": [run(1, "tests"), run(2, "review")]},
        "issue_comments": [claude_review(), codex_review()],
        "review_comments": [],
        "allowed": ["merge_check.py", "test_merge_check.py"],
    }
    data.update(parts)
    return data


def with_pull(**changes):
    pull = snapshot()["pull"]
    pull.update(changes)
    return pull


def files(*names):
    return [{"filename": name} for name in names]


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

    def says(self, data, expected):
        result = self.run_program(self.write(data))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout, (expected + "\n").encode("utf-8"))
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


class TestRules(Case):
    def test_v1_all_rules_pass(self):
        self.says(snapshot(), "MERGE")

    def test_v2_draft_and_closed_pull_requests(self):
        self.says(snapshot(pull=with_pull(draft=True)), "OWNER: not-open")
        self.says(snapshot(pull=with_pull(state="closed")), "OWNER: not-open")

    def test_v3_highest_run_id_counts(self):
        passing = {"check_runs": [run(10, "tests", conclusion="failure"), run(11, "tests"), run(12, "review")]}
        self.says(snapshot(check_runs=passing), "MERGE")
        failing = {"check_runs": [run(10, "tests"), run(11, "tests", conclusion="failure"), run(12, "review")]}
        self.says(snapshot(check_runs=failing), "OWNER: checks")

    def test_v3_unfinished_missing_and_custom_required_checks(self):
        pending = {"check_runs": [run(1, "tests"), run(2, "review", status="in_progress", conclusion=None)]}
        self.says(snapshot(check_runs=pending), "OWNER: checks")
        self.says(snapshot(check_runs={"check_runs": [run(1, "tests")]}), "OWNER: checks")
        custom = {"check_runs": [run(1, "ci", conclusion="failure"), run(2, "review")]}
        self.says(snapshot(check_runs=custom, required_checks=["ci", "review"]), "OWNER: checks")
        fine = {"check_runs": [run(1, "ci"), run(2, "review")]}
        self.says(snapshot(check_runs=fine, required_checks=["ci", "review"]), "MERGE")

    def test_v4_claude_review_for_an_older_head(self):
        self.says(snapshot(issue_comments=[claude_review(sha=H2), codex_review()]), "OWNER: claude-review")

    def test_v4_claude_verdict_fail(self):
        self.says(snapshot(issue_comments=[claude_review(verdict="FAIL"), codex_review()]), "OWNER: claude-review")

    def test_v4_head_line_must_be_the_second_line(self):
        body = "## Automatic review\nBLOCKING:\n- none\nHEAD: %s\nVERDICT: PASS" % H
        self.says(snapshot(issue_comments=[comment(1, CLAUDE, body), codex_review()]), "OWNER: claude-review")
        first = "HEAD: %s\nVERDICT: PASS" % H
        self.says(snapshot(issue_comments=[comment(1, CLAUDE, first), codex_review()]), "OWNER: claude-review")

    def test_v5_no_codex_comment(self):
        self.says(snapshot(issue_comments=[claude_review()]), "OWNER: codex-review")

    def test_v5_codex_reviewed_another_commit(self):
        self.says(
            snapshot(issue_comments=[claude_review(), codex_review(sha="fedcba9876")]),
            "OWNER: codex-review",
        )

    def test_v5_codex_suggestions_instead_of_the_clean_phrase(self):
        body = "Reviewed commit: `%s`\n\nHere are some automated review suggestions" % H[:10]
        self.says(
            snapshot(issue_comments=[claude_review(), comment(2, CODEX, body)]),
            "OWNER: codex-review",
        )

    def test_v6_p1_badge_on_the_head_commit(self):
        data = snapshot(review_comments=[review_comment(5, "![P1 Badge](x) Crashes on empty input")])
        self.says(data, "OWNER: codex-p1")
        zero = snapshot(review_comments=[review_comment(5, "![P0 Badge](x) Worse")])
        self.says(zero, "OWNER: codex-p1")

    def test_v6_p1_badge_on_an_older_commit_is_not_reported(self):
        data = snapshot(review_comments=[review_comment(5, "![P1 Badge](x) old", commit_id=H2)])
        self.says(data, "MERGE")

    def test_v7_file_matching_no_allowed_pattern(self):
        data = snapshot(files=files("merge_check.py", "other.py"))
        self.says(data, "OWNER: paths")

    def test_v7_star_crosses_slashes(self):
        data = snapshot(
            files=files("apps/backend/src/a/b/c.ts", "apps/backend/src/x.ts"),
            allowed=["apps/backend/src/*"],
        )
        self.says(data, "MERGE")
        outside = snapshot(files=files("apps/frontend/src/x.ts"), allowed=["apps/backend/src/*"])
        self.says(outside, "OWNER: paths")

    def test_v8_workflow_file_is_protected(self):
        data = snapshot(files=files(".github/workflows/ci.yml"), allowed=[".github/*"])
        self.says(data, "OWNER: protected")
        both = snapshot(files=files(".github/workflows/ci.yml"))
        self.says(both, "OWNER: paths, protected")

    def test_v8_docs_and_exact_name_prefixes(self):
        self.says(snapshot(files=files("docs/x.md"), allowed=["docs/*"]), "OWNER: protected")
        self.says(snapshot(files=files("AGENTS.md"), allowed=["*"]), "OWNER: protected")
        self.says(snapshot(files=files("CLAUDE.md"), allowed=["*"]), "OWNER: protected")
        self.says(snapshot(files=files("apps/backend/prisma/schema.prisma"), allowed=["*"]), "OWNER: protected")
        # A prefix without a slash matches only that exact name.
        self.says(snapshot(files=files("AGENTS.md.bak", "docsy/x.md"), allowed=["*"]), "MERGE")

    def test_v8_custom_protected_list_adds_to_the_default(self):
        # Superseded by build request #50 (H1): a custom list only adds prefixes.
        data = snapshot(files=files("docs/x.md"), allowed=["docs/*"], protected=["secret/"])
        self.says(data, "OWNER: protected")
        data = snapshot(files=files("secret/key.txt"), allowed=["*"], protected=["secret/"])
        self.says(data, "OWNER: protected")
        data = snapshot(files=files("secret"), allowed=["*"], protected=["secret"])
        self.says(data, "OWNER: protected")
        data = snapshot(files=files(".github/ci.yml"), allowed=["*"], protected=[])
        self.says(data, "OWNER: protected")

    def test_v9_open_questions_none(self):
        for text in ("none", "- none", "None", "  - NONE  ", ""):
            with self.subTest(text=text):
                body = "## Summary\nx\n\n## Open questions\n%s\n\n## Tests\nall\n" % text
                self.says(snapshot(pull=with_pull(body=body)), "MERGE")

    def test_v9_open_questions_listed(self):
        body = "## Open questions\n1. Where does the file go?\n"
        self.says(snapshot(pull=with_pull(body=body)), "OWNER: open-question")
        body = "## Open questions\n- none\n- something else\n"
        self.says(snapshot(pull=with_pull(body=body)), "OWNER: open-question")
        body = "# open question\n\nWhich one?\n## Next\nnone"
        self.says(snapshot(pull=with_pull(body=body)), "OWNER: open-question")

    def test_v9_no_heading_passes(self):
        self.says(snapshot(pull=with_pull(body="Just a summary.")), "MERGE")
        self.says(snapshot(pull=with_pull(body=None)), "MERGE")
        self.says(snapshot(pull=with_pull(body="")), "MERGE")
        body = "## Summary\n**Question 1 Where does it go?**\n"
        self.says(snapshot(pull=with_pull(body=body)), "MERGE")

    def test_v10_several_failures_in_rule_order(self):
        data = snapshot(
            pull=with_pull(state="closed", body="## Open questions\nWhy?"),
            files=files(".github/x.yml"),
            check_runs={"check_runs": []},
            issue_comments=[],
            review_comments=[review_comment(3, "P1 Badge")],
            allowed=["nothing"],
        )
        self.says(
            data,
            "OWNER: not-open, checks, claude-review, codex-review, codex-p1, paths, protected, open-question",
        )
        some = snapshot(files=files("docs/a.md"), issue_comments=[codex_review()], allowed=["x"])
        self.says(some, "OWNER: claude-review, paths, protected")

    def test_v11_bad_arguments(self):
        self.bad()
        path = self.write(snapshot())
        self.bad(path, path)

    def test_v11_missing_and_unreadable_files(self):
        self.bad(os.path.join(self.folder, "missing.json"))
        self.bad(self.folder)

    def test_v11_not_json(self):
        self.bad(self.write(b"this is not json"))
        self.bad(self.write(b""))
        self.bad(self.write(b"\xff\xfe{}"))

    def test_v11_nan_and_infinity(self):
        text = json.dumps(snapshot())[:-1]
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                self.bad(self.write((text + ',"extra":' + constant + "}").encode("utf-8")))
        raw = json.dumps(snapshot()).replace('"number": 7', '"number": NaN')
        self.bad(self.write(raw.encode("utf-8")))

    def test_v11_short_head_sha(self):
        data = snapshot()
        data["pull"]["head"]["sha"] = H[:39]
        self.bad_snapshot(data)

    def test_v11_empty_allowed(self):
        self.bad_snapshot(snapshot(allowed=[]))

    def test_v12_existing_tests_still_pass(self):
        mine = os.path.basename(__file__)
        modules = sorted(
            os.path.basename(path)[:-3]
            for path in glob.glob(os.path.join(HERE, "test_*.py"))
            if os.path.basename(path) != mine
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


class TestExtra(Case):
    def test_extra_claude_review_needs_the_claude_bot(self):
        body = "x\nHEAD: %s\nVERDICT: PASS" % H
        fake = claude_review()
        fake["user"]["login"] = "someone-else"
        self.says(snapshot(issue_comments=[fake, codex_review()]), "OWNER: claude-review")
        del body

    def test_extra_highest_claude_comment_for_the_head_decides(self):
        old_pass = claude_review(comment_id=1)
        new_fail = claude_review(verdict="FAIL", comment_id=9)
        self.says(snapshot(issue_comments=[old_pass, new_fail, codex_review()]), "OWNER: claude-review")
        old_fail = claude_review(verdict="FAIL", comment_id=1)
        new_pass = claude_review(comment_id=9)
        self.says(snapshot(issue_comments=[new_pass, old_fail, codex_review()]), "MERGE")
        # A later comment for another head does not take the decision away.
        self.says(snapshot(issue_comments=[claude_review(), claude_review(sha=H2, verdict="FAIL", comment_id=9), codex_review()]), "MERGE")

    def test_extra_claude_lines_with_carriage_returns(self):
        body = "## Automatic review\r\nHEAD: %s\r\nVERDICT: PASS\r\n" % H
        self.says(snapshot(issue_comments=[comment(1, CLAUDE, body), codex_review()]), "MERGE")

    def test_extra_claude_head_line_must_be_exact(self):
        for second in ("HEAD: " + H + " ", "head: " + H, "HEAD:" + H, "HEAD: " + H[:39]):
            with self.subTest(second=second):
                body = "x\n%s\nVERDICT: PASS" % second
                self.says(snapshot(issue_comments=[comment(1, CLAUDE, body), codex_review()]), "OWNER: claude-review")

    def test_extra_claude_verdict_must_be_a_whole_line(self):
        body = "x\nHEAD: %s\nVERDICT: PASS because yes" % H
        self.says(snapshot(issue_comments=[comment(1, CLAUDE, body), codex_review()]), "OWNER: claude-review")

    def test_extra_codex_accepts_stars_spaces_and_the_curly_apostrophe(self):
        body = "**Reviewed commit:** `%s`\n\nDidn’t find any major issues" % H[:7]
        self.says(snapshot(issue_comments=[claude_review(), comment(2, CODEX, body)]), "MERGE")
        body = "Reviewed commit:`%s` Didn't find any major issues" % H
        self.says(snapshot(issue_comments=[claude_review(), comment(2, CODEX, body)]), "MERGE")

    def test_extra_codex_prefix_length_and_form(self):
        for token in (H[:6], H + "0", "xyz1234", "0123456"[:6] + "G"):
            with self.subTest(token=token):
                body = "Reviewed commit: `%s`\nDidn't find any major issues" % token
                self.says(
                    snapshot(issue_comments=[claude_review(), comment(2, CODEX, body)]),
                    "OWNER: codex-review",
                )
        body = "Reviewed commit: %s\nDidn't find any major issues" % H[:10]
        self.says(snapshot(issue_comments=[claude_review(), comment(2, CODEX, body)]), "OWNER: codex-review")

    def test_extra_codex_highest_comment_for_the_head_decides(self):
        clean = codex_review(comment_id=2)
        suggestions = comment(8, CODEX, "Reviewed commit: `%s`\nSuggestions" % H[:10])
        self.says(snapshot(issue_comments=[claude_review(), clean, suggestions]), "OWNER: codex-review")
        late_clean = codex_review(comment_id=9)
        early = comment(1, CODEX, "Reviewed commit: `%s`\nSuggestions" % H[:10])
        self.says(snapshot(issue_comments=[claude_review(), late_clean, early]), "MERGE")
        other = codex_review(sha="fedcba9876", comment_id=20)
        self.says(snapshot(issue_comments=[claude_review(), clean, other]), "MERGE")

    def test_extra_codex_comment_must_come_from_the_codex_bot(self):
        fake = codex_review()
        fake["user"]["login"] = "someone-else"
        self.says(snapshot(issue_comments=[claude_review(), fake]), "OWNER: codex-review")

    def test_extra_codex_p1_only_from_codex_and_only_badges(self):
        ok = snapshot(review_comments=[
            review_comment(5, "P2 Badge minor"),
            review_comment(6, "![P1 Badge](x)", login="someone-else"),
            review_comment(7, "no badge here"),
        ])
        self.says(ok, "MERGE")

    def test_extra_not_open_still_lets_other_rules_run(self):
        data = snapshot(pull=with_pull(draft=True), allowed=["x"])
        self.says(data, "OWNER: not-open, paths")

    def test_extra_no_changed_files_is_a_paths_reason(self):
        self.says(snapshot(files=[]), "OWNER: paths")

    def test_extra_open_question_stops_at_the_next_heading(self):
        body = "## Open questions\nnone\n## Tests\nWhy is this?\n"
        self.says(snapshot(pull=with_pull(body=body)), "MERGE")
        body = "## Open questions\n\n\n"
        self.says(snapshot(pull=with_pull(body=body)), "MERGE")
        body = "## Open questions\r\nnone\r\n## Tests\r\nx"
        self.says(snapshot(pull=with_pull(body=body)), "MERGE")

    def test_extra_every_open_question_heading_counts(self):
        body = "## Open questions\nnone\n\n### Open question\nWhy?\n"
        self.says(snapshot(pull=with_pull(body=body)), "OWNER: open-question")

    def test_extra_extra_keys_and_fields_are_ignored(self):
        data = snapshot(extra={"a": [1, 2]}, another=None)
        data["pull"]["title"] = "x"
        data["files"][0]["status"] = "added"
        self.says(data, "MERGE")

    def test_extra_large_integer_in_an_ignored_field(self):
        digits = "1" + "0" * 4999
        text = json.dumps(snapshot())[:-1] + ',"extra":' + digits + "}"
        result = self.run_program(self.write(text.encode("utf-8")))
        self.assertEqual(result.stdout, b"MERGE\n")
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.returncode, 0)

    def test_extra_unicode_everywhere_is_fine(self):
        data = snapshot(
            files=files("café.py"),
            allowed=["café.py"],
            pull=with_pull(body="## Summary\n日本語\n## Open questions\nnone"),
        )
        self.says(data, "MERGE")

    def test_extra_bad_structures_exit_2(self):
        def edit(path, value):
            data = snapshot()
            target = data
            for key in path[:-1]:
                target = target[key]
            if value is KeyError:
                del target[path[-1]]
            else:
                target[path[-1]] = value
            return data

        cases = [
            [],
            "text",
            None,
            edit(["pull"], KeyError),
            edit(["files"], KeyError),
            edit(["check_runs"], KeyError),
            edit(["issue_comments"], KeyError),
            edit(["review_comments"], KeyError),
            edit(["allowed"], KeyError),
            edit(["pull"], []),
            edit(["pull", "number"], "7"),
            edit(["pull", "number"], True),
            edit(["pull", "number"], 7.5),
            edit(["pull", "state"], None),
            edit(["pull", "draft"], 0),
            edit(["pull", "draft"], "false"),
            edit(["pull", "head"], []),
            edit(["pull", "head", "sha"], H.upper()),
            edit(["pull", "head", "sha"], H + "0"),
            edit(["pull", "head", "sha"], 5),
            edit(["pull", "head", "sha"], KeyError),
            edit(["pull", "body"], 5),
            edit(["pull", "body"], KeyError),
            edit(["files"], {}),
            edit(["files"], ["a.py"]),
            edit(["files"], [{"filename": 5}]),
            edit(["files"], [{}]),
            edit(["check_runs"], []),
            edit(["check_runs", "check_runs"], {}),
            edit(["check_runs", "check_runs"], [5]),
            edit(["check_runs", "check_runs"], [{"id": "1", "name": "tests", "status": "completed", "conclusion": "success"}]),
            edit(["check_runs", "check_runs"], [{"id": True, "name": "tests", "status": "completed", "conclusion": "success"}]),
            edit(["check_runs", "check_runs"], [{"id": 1, "name": 5, "status": "completed", "conclusion": "success"}]),
            edit(["check_runs", "check_runs"], [{"id": 1, "name": "tests", "status": None, "conclusion": "success"}]),
            edit(["check_runs", "check_runs"], [{"id": 1, "name": "tests", "status": "completed", "conclusion": 5}]),
            edit(["check_runs", "check_runs"], [{"id": 1, "name": "tests", "status": "completed"}]),
            edit(["issue_comments"], {}),
            edit(["issue_comments"], [5]),
            edit(["issue_comments"], [{"id": 1, "user": {"login": CLAUDE}}]),
            edit(["issue_comments"], [{"id": 1, "user": {"login": 5}, "body": "x"}]),
            edit(["issue_comments"], [{"id": 1, "body": "x"}]),
            edit(["issue_comments"], [{"id": 1, "user": "abc", "body": "x"}]),
            edit(["issue_comments"], [{"id": 1, "user": {}, "body": "x"}]),
            edit(["issue_comments"], [{"id": 1, "user": None, "body": 5}]),
            edit(["files"], [{"filename": "a.py", "previous_filename": None}]),
            edit(["files"], [{"filename": "a.py", "previous_filename": 5}]),
            edit(["issue_comments"], [{"id": "1", "user": {"login": CLAUDE}, "body": "x"}]),
            edit(["issue_comments"], [{"id": 1, "user": {"login": CLAUDE}, "body": None}]),
            edit(["review_comments"], {}),
            edit(["review_comments"], [{"id": 1, "user": {"login": CODEX}, "body": "x"}]),
            edit(["review_comments"], [{"id": 1, "user": {"login": CODEX}, "body": "x", "commit_id": None}]),
            edit(["allowed"], "merge_check.py"),
            edit(["allowed"], [5]),
            edit(["protected"], "docs/"),
            edit(["protected"], [None]),
            edit(["required_checks"], []),
            edit(["required_checks"], "tests"),
            edit(["required_checks"], ["tests", "tests"]),
            edit(["required_checks"], ["tests", 5]),
            edit(["required_checks"], [""]),
        ]
        for case in cases:
            with self.subTest(case=json.dumps(case)[:120]):
                self.bad_snapshot(case)

    def test_extra_empty_argument_exits_2(self):
        self.bad("")

    def test_extra_error_never_echoes_input(self):
        name = "SECRET-NAME-12345"
        path = os.path.join(self.folder, name)
        result = self.run_program(path)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(name.encode(), result.stderr)
        data = snapshot(allowed=[name, 5])
        result = self.run_program(self.write(data))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(name.encode(), result.stderr)
        self.assertEqual(result.stdout, b"")

    def test_extra_odd_patterns_never_crash(self):
        for pattern in ("[", "[z-a]", "[!]", "**", "?", "[[]", "\\"):
            with self.subTest(pattern=pattern):
                result = self.run_program(self.write(snapshot(allowed=[pattern])))
                self.assertNotIn(b"Traceback", result.stderr)
                self.assertIn(result.returncode, (0, 2))
                if result.returncode == 0:
                    self.assertIn(result.stdout, (b"MERGE\n", b"OWNER: paths\n"))

    def test_extra_working_directory_does_not_matter(self):
        path = self.write(snapshot())
        result = self.run_program(path, cwd=os.path.dirname(self.folder))
        self.assertEqual(result.stdout, b"MERGE\n")

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
        self.assertEqual(imported, {"fnmatch", "json", "os", "re", "sys"})
        opens = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
        ]
        self.assertEqual(len(opens), 1)


class TestAmendments(Case):
    """Build request #48: amendments A1 to A5."""

    def test_a1_rename_from_a_protected_path(self):
        rename = {"filename": "src/x.yml", "status": "renamed", "previous_filename": ".github/workflows/x.yml"}
        # The old path is checked too, so it is also outside "src/*".
        self.says(snapshot(files=[rename], allowed=["src/*"]), "OWNER: paths, protected")
        self.says(snapshot(files=[rename], allowed=["*"]), "OWNER: protected")

    def test_a1_rename_from_a_path_that_is_not_allowed(self):
        rename = {"filename": "merge_check.py", "status": "renamed", "previous_filename": "old.py"}
        self.says(snapshot(files=[rename]), "OWNER: paths")

    def test_a1_rename_to_a_protected_path(self):
        rename = {"filename": "docs/x.md", "status": "renamed", "previous_filename": "x.md"}
        self.says(snapshot(files=[rename], allowed=["*"]), "OWNER: protected")

    def test_a1_rename_between_allowed_unprotected_paths_passes(self):
        rename = {"filename": "src/b.py", "status": "renamed", "previous_filename": "src/a.py"}
        self.says(snapshot(files=[rename], allowed=["src/*"]), "MERGE")

    def test_a1_previous_filename_must_be_a_string(self):
        for value in (5, None, True, ["a"], {}):
            with self.subTest(value=value):
                item = {"filename": "merge_check.py", "status": "renamed", "previous_filename": value}
                self.bad_snapshot(snapshot(files=[item]))

    def test_a2_verdict_on_the_third_line_passes(self):
        self.says(snapshot(issue_comments=[claude_review(), codex_review()]), "MERGE")

    def test_a2_fail_on_line_three_and_pass_later_does_not_count(self):
        body = "## Automatic review\nHEAD: %s\nVERDICT: FAIL\nBLOCKING:\n- x\nVERDICT: PASS" % H
        self.says(snapshot(issue_comments=[comment(1, CLAUDE, body), codex_review()]), "OWNER: claude-review")

    def test_a2_pass_anywhere_but_line_three_does_not_count(self):
        for body in (
            "## Automatic review\nHEAD: %s\nBLOCKING:\n- none\nVERDICT: PASS" % H,
            "## Automatic review\nHEAD: %s\nVERDICT: PASS" % H + "x",
            "## Automatic review\nHEAD: %s" % H,
            "## Automatic review\nHEAD: %s\n VERDICT: PASS" % H,
        ):
            with self.subTest(body=body):
                self.says(snapshot(issue_comments=[comment(1, CLAUDE, body), codex_review()]), "OWNER: claude-review")

    def test_a2_verdict_line_with_carriage_returns(self):
        body = "## Automatic review\r\nHEAD: %s\r\nVERDICT: PASS\r\n" % H
        self.says(snapshot(issue_comments=[comment(1, CLAUDE, body), codex_review()]), "MERGE")

    def test_a2_highest_id_comment_for_the_head_decides(self):
        late = "## Automatic review\nHEAD: %s\nBLOCKING:\nVERDICT: PASS" % H
        data = snapshot(issue_comments=[claude_review(comment_id=1), comment(9, CLAUDE, late), codex_review()])
        self.says(data, "OWNER: claude-review")

    def test_a3_deleted_account_comments_are_skipped(self):
        deleted = {"id": 1, "user": None, "body": "x"}
        data = snapshot(issue_comments=[deleted, claude_review(comment_id=2), codex_review(comment_id=3)])
        self.says(data, "MERGE")

    def test_a3_deleted_account_cannot_be_the_claude_review(self):
        body = "## Automatic review\nHEAD: %s\nVERDICT: PASS" % H
        data = snapshot(issue_comments=[{"id": 1, "user": None, "body": body}, codex_review()])
        self.says(data, "OWNER: claude-review")

    def test_a3_deleted_account_cannot_be_the_codex_review(self):
        body = "Reviewed commit: `%s`\nDidn't find any major issues" % H[:10]
        data = snapshot(issue_comments=[claude_review(), {"id": 2, "user": None, "body": body}])
        self.says(data, "OWNER: codex-review")

    def test_a3_deleted_account_review_comment_is_skipped(self):
        item = {"id": 5, "user": None, "body": "P1 Badge", "commit_id": H}
        self.says(snapshot(review_comments=[item]), "MERGE")

    def test_a3_user_that_is_not_an_object_with_a_login_is_bad_input(self):
        for user in ("abc", 5, [], {}, {"login": 5}, {"login": None}):
            with self.subTest(user=user):
                self.bad_snapshot(snapshot(issue_comments=[{"id": 1, "user": user, "body": "x"}]))
                item = {"id": 1, "user": user, "body": "x", "commit_id": H}
                self.bad_snapshot(snapshot(review_comments=[item]))

    def test_a4_nothing_changed_is_a_paths_reason(self):
        self.says(snapshot(files=[]), "OWNER: paths")

    def test_a4_nothing_changed_keeps_the_order_of_reasons(self):
        data = snapshot(files=[], pull=with_pull(draft=True), issue_comments=[])
        self.says(data, "OWNER: not-open, claude-review, codex-review, paths")

    def test_a5_none_with_a_full_stop_is_empty(self):
        for text in ("None.", "none.", "NONE.", "- none.", "- None.", "  - NONE.  "):
            with self.subTest(text=text):
                body = "## Open questions\n%s\n" % text
                self.says(snapshot(pull=with_pull(body=body)), "MERGE")

    def test_a5_other_text_is_still_a_question(self):
        for text in ("None..", "none. Really?", "1. Which table?", "- none.\n- none", "No."):
            with self.subTest(text=text):
                body = "## Open questions\n%s\n" % text
                self.says(snapshot(pull=with_pull(body=body)), "OWNER: open-question")

    def test_a5_hash_number_line_does_not_end_the_section(self):
        body = "## Open questions\n#123 needs an answer: which table?\n## Tests\nall"
        self.says(snapshot(pull=with_pull(body=body)), "OWNER: open-question")
        body = "## Open questions\n#123 is fixed\n"
        self.says(snapshot(pull=with_pull(body=body)), "OWNER: open-question")

    def test_a5_hash_number_line_before_the_heading_or_after_a_real_heading(self):
        body = "#123 is fixed\n## Open questions\n- none\n"
        self.says(snapshot(pull=with_pull(body=body)), "MERGE")
        body = "## Open questions\nnone.\n## Tests\n#123 is fixed\n"
        self.says(snapshot(pull=with_pull(body=body)), "MERGE")

    def test_a5_heading_forms_that_end_the_section(self):
        for heading in ("# Next", "## Next", "### Next", "##Next", "## "):
            with self.subTest(heading=heading):
                body = "## Open questions\nnone\n%s\nWhy is this?\n" % heading
                self.says(snapshot(pull=with_pull(body=body)), "MERGE")


def with_runs(runs, **extra):
    entry = {"check_runs": runs}
    entry.update(extra)
    return entry


class TestHardening(Case):
    """Build request #50: changes H1 to H5 (checks V1 to V6)."""

    # H1 / V1
    def test_h1_empty_protected_list_keeps_the_defaults(self):
        data = snapshot(files=files(".github/workflows/x.yml"), allowed=["*"], protected=[])
        self.says(data, "OWNER: protected")
        for name in ("docs/a.md", "apps/backend/prisma/m.sql", "AGENTS.md", "CLAUDE.md"):
            with self.subTest(name=name):
                self.says(snapshot(files=files(name), allowed=["*"], protected=[]), "OWNER: protected")

    def test_h1_listed_prefix_adds_to_the_defaults(self):
        data = snapshot(files=files("docs/a.md"), allowed=["*"], protected=["src/secret/"])
        self.says(data, "OWNER: protected")
        data = snapshot(files=files("src/secret/k.txt"), allowed=["*"], protected=["src/secret/"])
        self.says(data, "OWNER: protected")
        data = snapshot(files=files("src/other/k.txt"), allowed=["*"], protected=["src/secret/"])
        self.says(data, "MERGE")

    def test_h1_absent_list_still_uses_the_defaults(self):
        self.says(snapshot(files=files(".github/x.yml"), allowed=["*"]), "OWNER: protected")

    # H2 / V2
    def test_h2_mergeable_state_other_than_clean(self):
        for state in ("dirty", "behind", "blocked", "unstable", "unknown", "has_hooks", ""):
            with self.subTest(state=state):
                self.says(snapshot(pull=with_pull(mergeable_state=state)), "OWNER: not-mergeable")

    def test_h2_clean_absent_or_null_is_not_reported(self):
        self.says(snapshot(pull=with_pull(mergeable_state="clean")), "MERGE")
        self.says(snapshot(pull=with_pull(mergeable_state=None)), "MERGE")
        self.says(snapshot(), "MERGE")

    def test_h2_comes_right_after_not_open(self):
        data = snapshot(
            pull=with_pull(state="closed", mergeable_state="dirty"),
            check_runs={"check_runs": []},
        )
        self.says(data, "OWNER: not-open, not-mergeable, checks")

    def test_h2_state_that_is_not_a_string_is_bad_input(self):
        for value in (5, True, ["clean"], {}):
            with self.subTest(value=value):
                self.bad_snapshot(snapshot(pull=with_pull(mergeable_state=value)))

    # H3 / V3
    def test_h3_badge_in_the_codex_summary_comment(self):
        for badge in ("P1 Badge", "P0 Badge"):
            with self.subTest(badge=badge):
                body = "Codex Review: Didn't find any major issues.\n\n![%s](x) Crash\n\nReviewed commit: `%s`" % (badge, H[:10])
                data = snapshot(issue_comments=[claude_review(), comment(2, CODEX, body)])
                self.says(data, "OWNER: codex-p1")

    def test_h3_only_the_deciding_codex_comment_counts(self):
        old = "![P1 Badge](x) old\n\nReviewed commit: `%s`" % H[:10]
        data = snapshot(issue_comments=[claude_review(), comment(1, CODEX, old), codex_review(comment_id=2)])
        self.says(data, "MERGE")
        other = "![P1 Badge](x)\n\nReviewed commit: `%s`" % H2[:10]
        data = snapshot(issue_comments=[claude_review(), codex_review(), comment(3, CODEX, other)])
        self.says(data, "MERGE")
        stranger = "![P1 Badge](x)\n\nReviewed commit: `%s`" % H[:10]
        data = snapshot(issue_comments=[claude_review(), codex_review(), comment(3, "someone-else", stranger)])
        self.says(data, "MERGE")

    def test_h3_without_a_deciding_comment_only_codex_review_is_reported(self):
        self.says(snapshot(issue_comments=[claude_review()]), "OWNER: codex-review")

    # H4 / V4
    def test_h4_heading_like_line_in_a_fence_does_not_end_the_section(self):
        body = "## Open questions\n```\n# note\n```\n1. Which table?\n"
        self.says(snapshot(pull=with_pull(body=body)), "OWNER: open-question")

    def test_h4_fenced_heading_does_not_start_a_section(self):
        body = "## Summary\n```\n## Open questions\nWhich table?\n```\n"
        self.says(snapshot(pull=with_pull(body=body)), "MERGE")

    def test_h4_real_heading_after_the_fence_still_ends_the_section(self):
        body = "## Open questions\nnone\n```\n# x\n```\n"
        self.says(snapshot(pull=with_pull(body=body)), "OWNER: open-question")
        body = "## Open questions\nnone\n## Tests\n```\n# x\n```\n"
        self.says(snapshot(pull=with_pull(body=body)), "MERGE")

    def test_h4_unclosed_fence_runs_to_the_end(self):
        body = "## Open questions\n```\n## Tests\nall\n"
        self.says(snapshot(pull=with_pull(body=body)), "OWNER: open-question")

    # H5 / V5
    def test_h5_total_count_larger_than_the_list(self):
        runs = with_runs([run(1, "tests"), run(2, "review")], total_count=3)
        self.says(snapshot(check_runs=runs), "OWNER: checks")
        one = with_runs([run(1, "tests")], total_count=2)
        self.says(snapshot(check_runs=one), "OWNER: checks")

    def test_h5_total_count_equal_smaller_or_absent_is_not_reported(self):
        for total in (2, 1, 0, None):
            with self.subTest(total=total):
                runs = with_runs([run(1, "tests"), run(2, "review")], total_count=total)
                self.says(snapshot(check_runs=runs), "MERGE")

    def test_h5_total_count_that_is_not_an_integer_is_bad_input(self):
        for value in ("2", 2.5, True, [2]):
            with self.subTest(value=value):
                self.bad_snapshot(snapshot(check_runs=with_runs([run(1, "tests"), run(2, "review")], total_count=value)))

    def test_h5_files_truncated_reports_paths(self):
        self.says(snapshot(files_truncated=True), "OWNER: paths")

    def test_h5_files_truncated_false_or_null_is_not_reported(self):
        self.says(snapshot(files_truncated=False), "MERGE")
        self.says(snapshot(files_truncated=None), "MERGE")

    def test_h5_files_truncated_that_is_not_a_boolean_is_bad_input(self):
        for value in ("true", 1, [True]):
            with self.subTest(value=value):
                self.bad_snapshot(snapshot(files_truncated=value))

    def test_h5_both_reasons_together_in_rule_order(self):
        data = snapshot(
            check_runs=with_runs([run(1, "tests"), run(2, "review")], total_count=9),
            files_truncated=True,
        )
        self.says(data, "OWNER: checks, paths")


class TestOutputFailures(Case):
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
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full not available")
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
             "import os, sys\nos.close(1)\nsys.argv = ['merge_check.py', sys.argv[1]]\n"
             "import runpy\nrunpy.run_path(%r, run_name='__main__')" % PROGRAM,
             path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.folder,
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_extra_unwritable_stderr_still_gives_status_2(self):
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

    def test_extra_unwritable_stderr_with_a_bad_snapshot(self):
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full not available")
        path = self.write(b"not json")
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


if __name__ == "__main__":
    unittest.main()
