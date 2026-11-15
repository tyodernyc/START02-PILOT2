"""Tests for draft_followup.py (build request #42).

Every check V1 to V10 of the request has one test method named after it.
Each case runs the program as a separate process and compares standard
output, standard error and the exit status exactly. The tests named
test_extra_* cover the rest of the specification (S1 to S7).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "draft_followup.py")
ERROR_PREFIX = b"draft_followup: "

H = "0123456789abcdef0123456789abcdef01234567"
H2 = "fedcba9876543210fedcba9876543210fedcba98"
BOT = "claude[bot]"


def pull(number=5, sha=H):
    return {"number": number, "head": {"ref": "req-1", "sha": sha}}


def comment(cid, body, login=BOT):
    return {"id": cid, "user": {"login": login}, "body": body}


def review_body(items, sha=H, extra_before="", after=""):
    lines = ["## Review", "HEAD: " + sha, "", "BLOCKING:", "- none", "",
             "LEFTOVER:"]
    lines += ["- " + item for item in items]
    text = "\n".join(lines) + "\n"
    return extra_before + text + after


def template(number, sha, items):
    out = (
        "TITLE: Build request: follow-up to pull request %d\n"
        "## Request\n"
        "\n"
        "Follow up the LEFTOVER findings of the automatic review of pull "
        "request %d (head commit %s). Check each finding against the code as "
        "it is now. Fix only what you reproduce and what lies within the "
        "allowed paths; for anything else, say why it was not fixed.\n"
        "\n"
        "## Findings\n"
        "\n" % (number, number, sha)
    )
    for index, item in enumerate(items, 1):
        out += "%d. %s\n" % (index, item)
    out += (
        "\n"
        "## Deliverables\n"
        "\n"
        "- Allowed paths: TO BE FILLED IN BY THE COORDINATOR BEFORE FILING.\n"
        "- A test for each fix. All existing tests keep passing.\n"
        "- Do not merge.\n"
        "\n"
        "## Decide and record\n"
        "\n"
        "Where this request is silent, make the simplest choice consistent "
        "with the findings and list it in the pull request body under "
        '"Assumptions". Do not stop to ask.\n'
    )
    return out.encode("utf-8")


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def path(self, name):
        return os.path.join(self.dir.name, name)

    def write(self, name, content):
        if not isinstance(content, bytes):
            content = json.dumps(content).encode("utf-8")
        with open(self.path(name), "wb") as handle:
            handle.write(content)
        return self.path(name)

    def run_args(self, args):
        done = subprocess.run(
            [sys.executable, PROGRAM] + list(args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.dir.name,
        )
        return done.returncode, done.stdout, done.stderr

    def run_data(self, pull_data, comments_data):
        return self.run_args([
            self.write("pull.json", pull_data),
            self.write("comments.json", comments_data),
        ])

    def ok(self, pull_data, comments_data, expected):
        code, out, err = self.run_data(pull_data, comments_data)
        self.assertEqual((code, err), (0, b""))
        self.assertEqual(out, expected)

    def bad(self, args):
        code, out, err = self.run_args(args)
        self.assertEqual(code, 2)
        self.assertEqual(out, b"")
        self.assertTrue(err.startswith(ERROR_PREFIX), err)
        self.assertTrue(err.endswith(b"\n"))
        self.assertEqual(err.count(b"\n"), 1)
        self.assertNotIn(b"Traceback", err)

    def items_out(self, items, comments_data=None, number=5, sha=H):
        if comments_data is None:
            comments_data = [comment(1, review_body(items, sha))]
        return self.run_data(pull(number, sha), comments_data)


class DraftTests(Case):
    def test_v1_two_items(self):
        items = ["first finding", "second finding"]
        self.ok(pull(5), [comment(1, review_body(items))],
                template(5, H, items))

    def test_v2_no_review(self):
        nothing = b"NO REVIEW\n"
        self.ok(pull(), [], nothing)
        self.ok(pull(), [comment(1, review_body(["x"]), login="someone")],
                nothing)
        self.ok(pull(), [comment(1, review_body(["x"], sha=H2))], nothing)
        late = "## Review\n\nintro\nHEAD: " + H + "\nLEFTOVER:\n- x\n"
        self.ok(pull(), [comment(1, late)], nothing)

    def test_v3_highest_id_wins(self):
        comments = [
            comment(11, review_body(["new"])),
            comment(10, review_body(["old"])),
        ]
        self.ok(pull(), comments, template(5, H, ["new"]))
        self.ok(pull(), list(reversed(comments)), template(5, H, ["new"]))

    def test_v4_no_leftovers(self):
        none = b"NO LEFTOVERS\n"
        self.ok(pull(), [comment(1, review_body([]) + "- none\n")], none)
        self.ok(pull(), [comment(1, review_body(["none"]))], none)
        body = "## Review\nHEAD: " + H + "\nBLOCKING:\n- none\n"
        self.ok(pull(), [comment(1, body)], none)

    def test_v5_items_stop_at_next_heading(self):
        body = review_body(["kept 1", "kept 2"], after="NOTES:\n- x\n- y\n")
        self.ok(pull(), [comment(1, body)],
                template(5, H, ["kept 1", "kept 2"]))
        plain = ("## Review\nHEAD: " + H + "\nLEFTOVER:\n- a\nplain line\n"
                 "\n- b\nVERDICT:\n- c\n")
        self.ok(pull(), [comment(1, plain)], template(5, H, ["a", "b"]))

    def test_v6_at_signs(self):
        items = ["see a@b.example", "@@@"]
        code, out, err = self.items_out(items)
        self.assertEqual((code, err), (0, b""))
        self.assertEqual(
            out, template(5, H, ["see a(at)b.example", "(at)(at)(at)"]))
        self.assertNotIn(b"@", out)

    def test_v7_controls_and_length(self):
        items = ["tab\there\x07bell", "y" * 1500]
        self.ok(pull(), [comment(1, review_body(items))],
                template(5, H, ["tabherebell", "y" * 1000 + "..."]))

    def test_v8_carriage_returns(self):
        body = review_body(["one", "two"], after="NOTES:\n- no\n")
        crlf = body.replace("\n", "\r\n")
        self.ok(pull(), [comment(1, crlf)], template(5, H, ["one", "two"]))
        code, out, err = self.run_data(pull(), [comment(1, body)])
        code2, out2, err2 = self.run_data(pull(), [comment(1, crlf)])
        self.assertEqual((code, out, err), (code2, out2, err2))

    def test_v9_template_byte_for_byte(self):
        items = ["only one"]
        code, out, err = self.items_out(items, number=123)
        self.assertEqual((code, err), (0, b""))
        self.assertEqual(out, template(123, H, items))
        lines = out.split(b"\n")
        self.assertEqual(lines[0],
                         b"TITLE: Build request: follow-up to pull request 123")
        self.assertEqual(lines[-1], b"")
        self.assertEqual(out.count(b"\r"), 0)

    def test_v10_bad_input(self):
        good_pull = self.write("pull.json", pull())
        good_comments = self.write("comments.json", [])
        self.bad([])
        self.bad([good_pull])
        self.bad([good_pull, good_comments, good_comments])
        self.bad([good_pull, self.path("missing.json")])
        self.bad([self.path("missing.json"), good_comments])
        self.bad([self.write("notjson.json", b"not json"), good_comments])
        self.bad([good_pull, self.write("notjson2.json", b"{bad")])
        self.bad([self.write("p1.json", pull(number=True)), good_comments])
        self.bad([self.write("p2.json", pull(sha=H[:39])), good_comments])
        self.bad([good_pull,
                  self.write("c1.json", [{"id": 1, "user": {"login": BOT}}])])


class ExtraTests(Case):
    def test_extra_pull_structure(self):
        comments = self.write("c.json", [])
        cases = [
            [],
            {"number": 5},
            {"number": 0, "head": {"sha": H}},
            {"number": 1.5, "head": {"sha": H}},
            {"number": 5, "head": "x"},
            {"number": 5, "head": {"sha": 5}},
            {"number": 5, "head": {"sha": H.upper()}},
            {"number": 5, "head": {"sha": H + "0"}},
            {"number": 5, "head": {"sha": H + "\n"}},
        ]
        for index, data in enumerate(cases):
            self.bad([self.write("p%d.json" % index, data), comments])

    def test_extra_comment_structure(self):
        good_pull = self.write("pull.json", pull())
        bad_lists = [
            {},
            [5],
            [{"id": True, "user": {"login": BOT}, "body": "x"}],
            [{"id": "1", "user": {"login": BOT}, "body": "x"}],
            [{"id": 1, "user": None, "body": "x"}],
            [{"id": 1, "user": {"login": 5}, "body": "x"}],
            [{"id": 1, "user": {"login": BOT}, "body": None}],
        ]
        for index, data in enumerate(bad_lists):
            self.bad([good_pull, self.write("c%d.json" % index, data)])

    def test_extra_not_utf8(self):
        good_comments = self.write("comments.json", [])
        self.bad([self.write("latin.json", b'{"number": "\xe9"}'),
                  good_comments])

    def test_extra_other_fields_ignored(self):
        data = pull()
        data["extra"] = {"anything": [1, 2]}
        item = comment(3, review_body(["a"]))
        item["created_at"] = "2026-01-01T00:00:00Z"
        self.ok(data, [item], template(5, H, ["a"]))

    def test_extra_item_edges(self):
        items = ["  padded  ", "\x01\x02", "@", "keep: colon", "tail \x7f"]
        body = review_body(items)
        self.ok(pull(), [comment(1, body)],
                template(5, H, ["padded", "(at)", "keep: colon", "tail"]))

    def test_extra_cut_text_not_stripped_before_cut(self):
        items = ["z" * 1000, "z" * 1001]
        self.ok(pull(), [comment(1, review_body(items))],
                template(5, H, ["z" * 1000, "z" * 1000 + "..."]))

    def test_extra_review_must_be_second_line(self):
        body = "HEAD: " + H + "\nLEFTOVER:\n- x\n"
        self.ok(pull(), [comment(1, body)], b"NO REVIEW\n")
        self.ok(pull(), [comment(1, "one line")], b"NO REVIEW\n")
        self.ok(pull(), [comment(1, "")], b"NO REVIEW\n")
        prefix = "## Review\nHEAD: " + H + "x\nLEFTOVER:\n- x\n"
        self.ok(pull(), [comment(1, prefix)], b"NO REVIEW\n")

    def test_extra_lone_surrogate_does_not_crash(self):
        raw = ('[{"id": 1, "user": {"login": "claude[bot]"}, "body": '
               '"## R\\nHEAD: ' + H + '\\nLEFTOVER:\\n- a' + "\\ud800" +
               '\\n"}]').encode("utf-8")
        code, out, err = self.run_args([
            self.write("pull.json", pull()), self.write("c.json", raw)])
        self.assertEqual((code, err), (0, b""))
        self.assertIn(b"1. a", out)

    def test_extra_unwritable_output_exits_1(self):
        pull_path = self.write("pull.json", pull())
        comments_path = self.write(
            "comments.json", [comment(1, review_body(["x"]))])
        if not os.path.exists("/dev/full"):
            self.skipTest("no /dev/full")
        with open("/dev/full", "wb") as full:
            done = subprocess.run(
                [sys.executable, PROGRAM, pull_path, comments_path],
                stdin=subprocess.DEVNULL, stdout=full,
                stderr=subprocess.PIPE)
        self.assertEqual(done.returncode, 1)
        self.assertNotIn(b"Traceback", done.stderr)

    def test_extra_inputs_not_modified(self):
        pull_path = self.write("pull.json", pull())
        comments_path = self.write(
            "comments.json", [comment(1, review_body(["x"]))])
        def snapshot():
            data = []
            for name in (pull_path, comments_path):
                with open(name, "rb") as handle:
                    data.append(handle.read())
            return data

        before = snapshot()
        self.run_args([pull_path, comments_path])
        after = snapshot()
        self.assertEqual(before, after)
        self.assertEqual(sorted(os.listdir(self.dir.name)),
                         ["comments.json", "pull.json"])


if __name__ == "__main__":
    unittest.main()
