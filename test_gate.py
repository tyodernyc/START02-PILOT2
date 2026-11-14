import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GATE_PATH = os.path.join(HERE, ".github", "scripts", "review_gate.py")

spec = importlib.util.spec_from_file_location("review_gate", GATE_PATH)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

HEAD = "a" * 40
OTHER_HEAD = "b" * 40
START = "2026-11-12T10:00:00Z"
BEFORE = "2026-11-12T09:59:59Z"
AFTER = "2026-11-12T10:00:40Z"
LATER = "2026-11-12T10:01:30Z"


def review(verdict="PASS", head=HEAD, created=AFTER, login="claude[bot]", body=None):
    if body is None:
        body = (
            "## Automatic review\n"
            "HEAD: %s\n"
            "VERDICT: %s\n"
            "BLOCKING:\n- none\nLEFTOVER:\n- none" % (head, verdict)
        )
    return {"user": {"login": login}, "created_at": created, "body": body}


def filler(number, created=AFTER):
    return {
        "user": {"login": "tyodernyc"},
        "created_at": created,
        "body": "filler %d" % number,
    }


class TestDecide(unittest.TestCase):
    def passed(self, comments, head=HEAD, start=START):
        return gate.decide(comments, head, start)[0]

    def test_fresh_pass(self):
        self.assertTrue(self.passed([review()]))

    def test_fresh_fail(self):
        self.assertFalse(self.passed([review("FAIL")]))

    def test_no_comments(self):
        self.assertFalse(self.passed([]))

    def test_old_pass_no_fresh_review(self):
        self.assertFalse(self.passed([review(created=BEFORE)]))

    def test_old_pass_new_fail(self):
        comments = [review(head=OTHER_HEAD, created=BEFORE), review("FAIL")]
        self.assertFalse(self.passed(comments))

    def test_pass_at_exact_start_time(self):
        self.assertTrue(self.passed([review(created=START)]))

    def test_wrong_head(self):
        self.assertFalse(self.passed([review(head=OTHER_HEAD)]))

    def test_short_head_in_comment(self):
        self.assertFalse(self.passed([review(head=HEAD[:7])]))

    def test_missing_head_line(self):
        body = "## Automatic review\nVERDICT: PASS\nBLOCKING:\n- none"
        self.assertFalse(self.passed([review(body=body)]))

    def test_two_head_lines(self):
        body = "## Automatic review\nHEAD: %s\nHEAD: %s\nVERDICT: PASS" % (HEAD, OTHER_HEAD)
        self.assertFalse(self.passed([review(body=body)]))

    def test_not_the_reviewer(self):
        self.assertFalse(self.passed([review(login="tyodernyc")]))

    def test_heading_not_first(self):
        body = "hello\n## Automatic review\nHEAD: %s\nVERDICT: PASS" % HEAD
        self.assertFalse(self.passed([review(body=body)]))

    def test_no_verdict_line(self):
        body = "## Automatic review\nHEAD: %s\nBLOCKING:\n- none" % HEAD
        self.assertFalse(self.passed([review(body=body)]))

    def test_two_verdict_lines(self):
        for second in ("FAIL", "PASS"):
            body = "## Automatic review\nHEAD: %s\nVERDICT: PASS\nVERDICT: %s" % (HEAD, second)
            self.assertFalse(self.passed([review(body=body)]))

    def test_unparseable_verdict(self):
        for verdict in ("PASS or FAIL", "pass", "PASSED", ""):
            self.assertFalse(self.passed([review(verdict)]))

    def test_trailing_space_and_crlf(self):
        body = "## Automatic review\r\nHEAD: %s \r\nVERDICT: PASS \r\nBLOCKING:\r\n- none" % HEAD
        self.assertTrue(self.passed([review(body=body)]))

    def test_newest_accepted_decides(self):
        self.assertFalse(self.passed([review("PASS"), review("FAIL", created=LATER)]))
        self.assertTrue(self.passed([review("FAIL"), review("PASS", created=LATER)]))

    def test_same_second_later_in_list_decides(self):
        self.assertFalse(self.passed([review("PASS"), review("FAIL")]))

    def test_more_than_100_comments(self):
        comments = [review(head=OTHER_HEAD, created=BEFORE)]
        comments += [filler(number) for number in range(150)]
        comments.append(review(created=LATER))
        self.assertTrue(self.passed(comments))
        comments[-1] = review("FAIL", created=LATER)
        self.assertFalse(self.passed(comments))

    def test_bad_created_time(self):
        self.assertFalse(self.passed([review(created="yesterday")]))
        self.assertFalse(self.passed([review(created=None)]))

    def test_bad_head_or_start(self):
        self.assertFalse(self.passed([review()], head=""))
        self.assertFalse(self.passed([review(head="A" * 40)], head="A" * 40))
        self.assertFalse(self.passed([review()], start=""))
        self.assertFalse(self.passed([review()], start="2026-11-12 10:00:00"))

    def test_odd_comment_shapes(self):
        odd = [{"user": None, "body": None}, {"body": 5, "user": {"login": "claude[bot]"}}, {}]
        self.assertFalse(self.passed(odd))
        self.assertTrue(self.passed(odd + [review()]))


class TestLoad(unittest.TestCase):
    def test_one_array(self):
        self.assertEqual(len(gate.load_comments(json.dumps([review(), filler(1)]))), 2)

    def test_array_of_pages(self):
        pages = [[filler(number) for number in range(100)], [review()]]
        self.assertEqual(len(gate.load_comments(json.dumps(pages))), 101)

    def test_arrays_one_after_another(self):
        text = json.dumps([filler(number) for number in range(100)]) + "\n" + json.dumps([review()])
        self.assertEqual(len(gate.load_comments(text)), 101)

    def test_empty_array(self):
        self.assertEqual(gate.load_comments("[]"), [])

    def test_unreadable(self):
        for text in ("", "   ", "not json", '{"message": "Not Found"}', "[1, 2]", "[[], 3]"):
            with self.assertRaises(ValueError):
                gate.load_comments(text)


class TestCommandLine(unittest.TestCase):
    def run_gate(self, text, head=HEAD, start=START):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "comments.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            env = dict(os.environ, HEAD_SHA=head, RUN_START=start)
            return subprocess.run(
                [sys.executable, GATE_PATH, path], capture_output=True, env=env
            )

    def test_pass_exits_zero(self):
        pages = json.dumps([filler(n) for n in range(100)]) + json.dumps([review()])
        result = self.run_gate(pages)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"GATE: 101 comments read; review verdict PASS", result.stdout)

    def test_fail_exits_one(self):
        self.assertEqual(self.run_gate(json.dumps([review("FAIL")])).returncode, 1)

    def test_stale_pass_exits_one(self):
        result = self.run_gate(json.dumps([review(created=BEFORE)]))
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"no review comment for this head commit", result.stdout)

    def test_unreadable_exits_one(self):
        self.assertEqual(self.run_gate("not json").returncode, 1)

    def test_missing_file_exits_one(self):
        env = dict(os.environ, HEAD_SHA=HEAD, RUN_START=START)
        result = subprocess.run(
            [sys.executable, GATE_PATH, os.path.join(HERE, "no-such-file.json")],
            capture_output=True,
            env=env,
        )
        self.assertEqual(result.returncode, 1)

    def test_missing_environment_exits_one(self):
        self.assertEqual(self.run_gate(json.dumps([review()]), head="", start="").returncode, 1)


if __name__ == "__main__":
    unittest.main()
