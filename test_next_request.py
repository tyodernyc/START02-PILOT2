"""Tests for next_request.py (build request #30).

Every numbered check N1 to N17 of the request has one test method named after
it. Each case runs the program as a separate process and compares standard
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
PROGRAM = os.path.join(HERE, "next_request.py")
ERROR_PREFIX = b"next_request: "


def issue(number, title="Build request: x", state="open", association="OWNER", **extra):
    """One element of the issues list; eligible unless an argument says otherwise."""
    item = {
        "number": number,
        "title": title,
        "state": state,
        "author_association": association,
    }
    item.update(extra)
    return item


def branch(name):
    return {"name": name}


def as_bytes(content):
    """File content: bytes are written as they are, anything else as JSON."""
    if isinstance(content, bytes):
        return content
    return json.dumps(content).encode("utf-8")


class ProgramCase(unittest.TestCase):
    def run_args(self, *args, env=None):
        return subprocess.run(
            [sys.executable, PROGRAM, *args],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=env,
        )

    def run_files(self, issues, branches, env=None):
        with tempfile.TemporaryDirectory() as folder:
            issues_path = os.path.join(folder, "issues.json")
            branches_path = os.path.join(folder, "branches.json")
            with open(issues_path, "wb") as handle:
                handle.write(as_bytes(issues))
            with open(branches_path, "wb") as handle:
                handle.write(as_bytes(branches))
            return self.run_args(issues_path, branches_path, env=env)

    def assert_answer(self, result, expected):
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


class TestNumberedChecks(ProgramCase):
    def test_n01_both_arrays_empty(self):
        self.assert_answer(self.run_files([], []), "NONE")

    def test_n02_one_eligible_issue(self):
        self.assert_answer(self.run_files([issue(5)], []), "5")

    def test_n03_lowest_number_wins_whatever_the_order(self):
        self.assert_answer(self.run_files([issue(7), issue(5)], []), "5")

    def test_n04_author_is_not_the_owner(self):
        for association in ("NONE", "CONTRIBUTOR", "COLLABORATOR", "MEMBER", "owner"):
            with self.subTest(association=association):
                result = self.run_files([issue(5, association=association)], [])
                self.assert_answer(result, "NONE")

    def test_n05_title_is_not_a_build_request(self):
        titles = (
            "build request: x",
            "Build request:x",
            "Build request: ",
            "Build request:    ",
            " Build request: x",
            "Please Build request: x",
            "",
        )
        for title in titles:
            with self.subTest(title=title):
                self.assert_answer(self.run_files([issue(5, title=title)], []), "NONE")

    def test_n06_pull_request_item(self):
        item = issue(5, pull_request={"url": "https://example.invalid/pulls/5"})
        self.assert_answer(self.run_files([item], []), "NONE")

    def test_n07_closed_issue(self):
        self.assert_answer(self.run_files([issue(5, state="closed")], []), "NONE")

    def test_n08_branch_already_exists(self):
        self.assert_answer(self.run_files([issue(5)], [branch("req-5")]), "NONE")
        self.assert_answer(self.run_files([issue(5), issue(7)], [branch("req-5")]), "7")

    def test_n09_similar_branch_names_do_not_count(self):
        branches = [branch("req-50"), branch("req-5x"), branch("xreq-5"), branch("REQ-5")]
        self.assert_answer(self.run_files([issue(5)], branches), "5")

    def test_n10_mixed_list(self):
        issues = [
            issue(3, pull_request={"url": "https://example.invalid/pulls/3"}),
            issue(4, association="CONTRIBUTOR"),
            issue(6, state="closed"),
            issue(12),
            issue(9),
        ]
        self.assert_answer(self.run_files(issues, [branch("req-9")]), "12")

    def test_n11_non_ascii_title(self):
        item = issue(5, title="Build request: caf\u00e9")
        raw = json.dumps([item], ensure_ascii=False).encode("utf-8")
        self.assertIn("caf\u00e9".encode("utf-8"), raw)
        self.assert_answer(self.run_files(raw, []), "5")
        escaped = json.dumps([item], ensure_ascii=True).encode("ascii")
        self.assertIn(b"caf\\u00e9", escaped)
        self.assert_answer(self.run_files(escaped, []), "5")

    def test_n12_content_is_not_utf8_json(self):
        latin_1 = json.dumps([issue(5, title="Build request: caf\u00e9")], ensure_ascii=False)
        cases = {
            "issues file not JSON": (b"not json", []),
            "branches file empty": ([issue(5)], b""),
            "issues file not valid UTF-8": (latin_1.encode("latin-1"), []),
        }
        for name, (issues, branches) in cases.items():
            with self.subTest(case=name):
                self.assert_bad_input(self.run_files(issues, branches))

    def test_n13_top_level_is_an_object(self):
        self.assert_bad_input(self.run_files({}, []))
        self.assert_bad_input(self.run_files(issue(5), []))
        self.assert_bad_input(self.run_files([issue(5)], {}))
        self.assert_bad_input(self.run_files([issue(5)], branch("main")))

    def test_n14_wrong_number_of_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            issues_path = os.path.join(folder, "issues.json")
            branches_path = os.path.join(folder, "branches.json")
            with open(issues_path, "wb") as handle:
                handle.write(as_bytes([issue(5)]))
            with open(branches_path, "wb") as handle:
                handle.write(as_bytes([]))
            self.assert_answer(self.run_args(issues_path, branches_path), "5")
            argument_lists = {
                "no arguments": (),
                "one argument": (issues_path,),
                "three arguments": (issues_path, branches_path, branches_path),
            }
            for name, arguments in argument_lists.items():
                with self.subTest(case=name):
                    self.assert_bad_input(self.run_args(*arguments))

    def test_n15_issues_file_does_not_exist(self):
        with tempfile.TemporaryDirectory() as folder:
            branches_path = os.path.join(folder, "branches.json")
            with open(branches_path, "wb") as handle:
                handle.write(as_bytes([]))
            missing = os.path.join(folder, "no-such-issues.json")
            self.assert_bad_input(self.run_args(missing, branches_path))

    def test_n16_invalid_issue_beside_an_eligible_one(self):
        no_title = issue(6)
        del no_title["title"]
        invalid = {
            "no title": no_title,
            "number is the text 6": issue("6"),
            "number is true": issue(True),
            "number is 0": issue(0),
            "element is a text string": "Build request: x",
            "title is a number": issue(6, title=6),
        }
        for name, element in invalid.items():
            for order in ("after", "before"):
                with self.subTest(case=name, order=order):
                    issues = [issue(5), element] if order == "after" else [element, issue(5)]
                    self.assert_bad_input(self.run_files(issues, []))

    def test_n17_invalid_branch(self):
        invalid = {
            "no name": {"commit": {"sha": "0" * 40}},
            "element is a text string": "main",
        }
        for name, element in invalid.items():
            for order in ("after", "before"):
                with self.subTest(case=name, order=order):
                    branches = [branch("main"), element]
                    if order == "before":
                        branches.reverse()
                    self.assert_bad_input(self.run_files([issue(5)], branches))


class TestRestOfSpecification(ProgramCase):
    def test_extra_other_invalid_issue_elements(self):
        def without(key):
            item = issue(6)
            del item[key]
            return item

        invalid = {
            "no number": without("number"),
            "no state": without("state"),
            "no author_association": without("author_association"),
            "number is false": issue(False),
            "number is negative": issue(-5),
            "number is null": issue(None),
            "number is 6.0": issue(6.0),
            "state is null": issue(6, state=None),
            "author_association is a list": issue(6, association=["OWNER"]),
            "title is null": issue(6, title=None),
            "element is null": None,
            "element is a number": 6,
            "element is a list": [issue(6)],
        }
        for name, element in invalid.items():
            with self.subTest(case=name):
                self.assert_bad_input(self.run_files([issue(5), element], []))

    def test_extra_invalid_element_that_is_not_eligible_anyway(self):
        closed_pull_request = issue(6, state="closed", pull_request={})
        del closed_pull_request["title"]
        self.assert_bad_input(self.run_files([issue(5), closed_pull_request], []))

    def test_extra_other_invalid_branch_elements(self):
        for name in (5, None, True, ["main"], {"name": "main"}):
            with self.subTest(name=name):
                self.assert_bad_input(self.run_files([issue(5)], [{"name": name}]))
        for element in (None, 5, [branch("main")]):
            with self.subTest(element=element):
                self.assert_bad_input(self.run_files([issue(5)], [element]))

    def test_extra_other_unreadable_or_malformed_files(self):
        cases = {
            "issues file empty": (b"", []),
            "branches file not JSON": ([issue(5)], b"[{]"),
            "branches file not valid UTF-8": ([issue(5)], b'[{"name": "\xff"}]'),
            "issues file is UTF-16": (json.dumps([issue(5)]).encode("utf-16"), []),
            "issues file starts with a byte order mark": (b"\xef\xbb\xbf[]", []),
            "issues top level is a string": (b'"[]"', []),
            "issues top level is null": (b"null", []),
            "branches top level is a number": ([issue(5)], b"5"),
            "two arrays one after another": (b"[] []", []),
            "NaN is not JSON": (b'[{"number": 5, "title": "Build request: x", '
                                b'"state": "open", "author_association": "OWNER", '
                                b'"score": NaN}]', []),
            "a repeated key is ambiguous": (b'[{"number": 5, "title": "Build request: x", '
                                            b'"state": "closed", "state": "open", '
                                            b'"author_association": "OWNER"}]', []),
            "nesting too deep to read": (b"[" * 200000 + b"]" * 200000, []),
        }
        for name, (issues, branches) in cases.items():
            with self.subTest(case=name):
                self.assert_bad_input(self.run_files(issues, branches))

    def test_extra_missing_branches_file_and_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            issues_path = os.path.join(folder, "issues.json")
            with open(issues_path, "wb") as handle:
                handle.write(as_bytes([issue(5)]))
            missing = os.path.join(folder, "no-such-branches.json")
            self.assert_bad_input(self.run_args(issues_path, missing))
            self.assert_bad_input(self.run_args(issues_path, folder))
            self.assert_bad_input(self.run_args(folder, issues_path))
            self.assert_bad_input(self.run_args(issues_path, ""))

    def test_extra_arguments_are_file_names_not_options(self):
        for arguments in (("--help",), ("-h", "--version"), ("--", "a", "b")):
            with self.subTest(arguments=arguments):
                self.assert_bad_input(self.run_args(*arguments))

    def test_extra_eligibility_details(self):
        cases = {
            "pull_request key holding null": ([issue(5, pull_request=None)], [], "NONE"),
            "state in another case": ([issue(5, state="Open")], [], "NONE"),
            "state with a space": ([issue(5, state="open ")], [], "NONE"),
            "association with a space": ([issue(5, association=" OWNER")], [], "NONE"),
            "title of tabs and line feeds": ([issue(5, title="Build request: \t\n")], [], "NONE"),
            "title of a no-break space": ([issue(5, title="Build request: \u00a0")], [], "NONE"),
            "two spaces then text": ([issue(5, title="Build request:  x")], [], "5"),
            "text then spaces": ([issue(5, title="Build request: x  ")], [], "5"),
            "several lines": ([issue(5, title="Build request: a\nb")], [], "5"),
            "unknown keys are ignored": (
                [issue(5, body="NONE", labels=[{"name": "bug"}], user={"login": "someone"})],
                [{"name": "main", "protected": True, "commit": {"sha": "0" * 40}}],
                "5",
            ),
            "same number twice": ([issue(5, state="closed"), issue(5)], [], "5"),
            "branch listed twice": ([issue(5), issue(8)], [branch("req-5"), branch("req-5")], "8"),
            "branch with leading zero": ([issue(5)], [branch("req-05")], "5"),
            "branch with a line feed": ([issue(5)], [branch("req-5\n")], "5"),
            "large number": ([issue(12345678901234567890)], [], "12345678901234567890"),
            "large number taken": (
                [issue(12345678901234567890)], [branch("req-12345678901234567890")], "NONE",
            ),
            "many issues": ([issue(n) for n in range(300, 0, -1)], [branch("req-1")], "2"),
        }
        for name, (issues, branches, expected) in cases.items():
            with self.subTest(case=name):
                self.assert_answer(self.run_files(issues, branches), expected)

    def test_extra_issue_number_has_no_upper_bound(self):
        digits = "9" * 5000
        issues = json.dumps([issue(5)]).replace(": 5,", ": %s," % digits).encode("ascii")
        self.assertIn(digits.encode("ascii"), issues)
        self.assert_answer(self.run_files(issues, []), digits)
        taken = json.dumps([branch("req-" + digits)]).encode("ascii")
        self.assert_answer(self.run_files(issues, taken), "NONE")

    def test_extra_same_file_for_both_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "empty.json")
            with open(path, "wb") as handle:
                handle.write(b" [ ] \n")
            self.assert_answer(self.run_args(path, path), "NONE")

    def test_extra_no_text_from_an_issue_is_printed(self):
        marker = "ZEBRA-MARKER"
        eligible = issue(5, title="Build request: " + marker, body=marker)
        result = self.run_files([eligible], [branch(marker)])
        self.assert_answer(result, "5")
        broken = issue(6, title="Build request: " + marker, state=marker)
        del broken["author_association"]
        for issues, branches in (
            ([eligible, broken], []),
            ([eligible], [{"name": 5, "label": marker}]),
            ((json.dumps([eligible]) + marker).encode("utf-8"), []),
        ):
            result = self.run_files(issues, branches)
            self.assert_bad_input(result)
            self.assertNotIn(marker.encode("ascii"), result.stderr)

    @unittest.skipUnless(os.name == "posix", "an empty environment is a POSIX case")
    def test_extra_runs_with_an_empty_environment(self):
        self.assert_answer(self.run_files([issue(7), issue(5)], [], env={}), "5")
        self.assert_bad_input(self.run_files(b"{", [], env={}))

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
                     "exec", "eval", "__import__", "input", "print"}
        self.assertEqual(names & forbidden, set())


if __name__ == "__main__":
    unittest.main()
