"""Tests for bundle.py (build request #60).

Every check V1 to V4 of build request #60 has at least one test method named
after it (V5, that every older test still passes, is the whole test run). Each
case runs the program as a separate process and compares standard output,
standard error and the exit status exactly. The tests named test_extra_* cover
the rest of the specification and the choices listed in the pull request.
"""

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "bundle.py")
ERROR_PREFIX = b"bundle: "


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Case(unittest.TestCase):
    """A scratch folder with a ROOT folder, and helpers to run the program on it."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = holder.name
        self.root = os.path.join(self.base, "root")
        os.mkdir(self.root)
        self.list_path = os.path.join(self.base, "list.txt")
        self.output = os.path.join(self.base, "out.md")

    def put(self, name, raw):
        path = os.path.join(self.root, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(raw)
        return path

    def listing(self, text):
        raw = text if isinstance(text, bytes) else text.encode("utf-8")
        with open(self.list_path, "wb") as handle:
            handle.write(raw)

    def run_program(self, *args):
        return subprocess.run(
            [sys.executable, PROGRAM] + list(args),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )

    def bundle(self):
        return self.run_program(self.root, self.list_path, self.output)

    def output_bytes(self):
        with open(self.output, "rb") as handle:
            return handle.read()

    def assert_bad(self, result, fragment=None):
        self.assertEqual(result.returncode, 2, result)
        self.assertEqual(result.stdout, b"")
        self.assertTrue(result.stderr.startswith(ERROR_PREFIX), result.stderr)
        self.assertEqual(result.stderr.count(b"\n"), 1)
        self.assertTrue(result.stderr.endswith(b"\n"))
        if fragment is not None:
            self.assertIn(fragment.encode("utf-8"), result.stderr)
        self.assertFalse(os.path.lexists(self.output))


class TestChecks(Case):
    def test_v1_two_files_hashes_and_order(self):
        first = b"hello\n"
        second = "café\nline two\n".encode("utf-8")
        self.put("b.txt", first)
        self.put("sub/a.txt", second)
        self.listing("b.txt\nsub/a.txt\n")
        result = self.bundle()
        self.assertEqual(result.returncode, 0, result)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(
            result.stdout,
            ("2 files, %d bytes, written to %s\n" % (len(first) + len(second), self.output)).encode("utf-8"),
        )
        expected = (
            "# Bundle\n"
            "Files: 2\n"
            "\n"
            "| # | Path | Bytes | SHA-256 |\n"
            "| --- | --- | --- | --- |\n"
            "| 1 | b.txt | %d | %s |\n"
            "| 2 | sub/a.txt | %d | %s |\n"
            "\n"
            "## 1. b.txt\n"
            "SHA-256: %s\n"
            "\n"
            "```\n"
            "hello\n"
            "```\n"
            "\n"
            "## 2. sub/a.txt\n"
            "SHA-256: %s\n"
            "\n"
            "```\n"
            "café\nline two\n"
            "```\n"
        ) % (len(first), sha(first), len(second), sha(second), sha(first), sha(second))
        self.assertEqual(self.output_bytes(), expected.encode("utf-8"))

    def test_v1_manifest_follows_list_order_not_name_order(self):
        self.put("a.txt", b"A")
        self.put("b.txt", b"B")
        self.listing("b.txt\na.txt\n")
        self.assertEqual(self.bundle().returncode, 0)
        text = self.output_bytes().decode("utf-8")
        self.assertLess(text.index("| 1 | b.txt |"), text.index("| 2 | a.txt |"))
        self.assertLess(text.index("## 1. b.txt"), text.index("## 2. a.txt"))

    def test_v2_four_backticks_get_a_fence_of_five(self):
        body = b"before\n````\ninside\n````\nafter\n"
        self.put("f.md", body)
        self.listing("f.md\n")
        self.assertEqual(self.bundle().returncode, 0)
        text = self.output_bytes().decode("utf-8")
        self.assertIn("\n`````\nbefore\n````\ninside\n````\nafter\n`````\n", text)

    def test_v2_longest_run_decides_and_minimum_is_three(self):
        self.put("none.txt", b"no ticks\n")
        self.put("one.txt", b"a ` b\n")
        self.put("three.txt", b"```\n")
        self.put("mixed.txt", b"`` and ````` and `\n")
        self.listing("none.txt\none.txt\nthree.txt\nmixed.txt\n")
        self.assertEqual(self.bundle().returncode, 0)
        text = self.output_bytes().decode("utf-8")
        self.assertIn("\n```\nno ticks\n```\n", text)
        self.assertIn("\n```\na ` b\n```\n", text)
        self.assertIn("\n````\n```\n````\n", text)
        self.assertIn("\n``````\n`` and ````` and `\n``````\n", text)

    def test_v3_bad_paths_each_exit_2(self):
        self.put("ok.txt", b"ok\n")
        for line in ("../x", "/abs", "a//b", "a/../b", "./a", "a/./b", "a/", "back\\slash", " lead", "trail "):
            with self.subTest(line=line):
                self.listing(line + "\n")
                self.assert_bad(self.bundle())

    def test_v3_repeated_path(self):
        self.put("a.txt", b"a\n")
        self.listing("a.txt\nb.txt\na.txt\n")
        self.put("b.txt", b"b\n")
        self.assert_bad(self.bundle(), "a.txt")

    def test_v3_folder(self):
        os.mkdir(os.path.join(self.root, "dir"))
        self.listing("dir\n")
        self.assert_bad(self.bundle(), "dir")

    def test_v3_links(self):
        self.put("real.txt", b"real\n")
        os.symlink("real.txt", os.path.join(self.root, "link.txt"))
        self.listing("link.txt\n")
        self.assert_bad(self.bundle(), "link.txt")

    def test_v3_link_pointing_outside_root(self):
        outside = os.path.join(self.base, "outside.txt")
        with open(outside, "wb") as handle:
            handle.write(b"secret\n")
        os.symlink(outside, os.path.join(self.root, "out.txt"))
        self.listing("out.txt\n")
        self.assert_bad(self.bundle(), "out.txt")

    def test_v3_link_in_a_folder_part(self):
        self.put("real/a.txt", b"a\n")
        os.symlink("real", os.path.join(self.root, "alias"))
        self.listing("alias/a.txt\n")
        self.assert_bad(self.bundle(), "alias/a.txt")

    def test_v3_missing_file(self):
        self.listing("missing.txt\n")
        self.assert_bad(self.bundle(), "missing.txt")

    def test_v3_non_utf8_file(self):
        self.put("bad.bin", b"ok \xff\xfe broken\n")
        self.listing("bad.bin\n")
        self.assert_bad(self.bundle(), "bad.bin")

    def test_v3_surrogate_encoded_file_is_not_utf8(self):
        self.put("sur.txt", b"\xed\xa0\x80")
        self.listing("sur.txt\n")
        self.assert_bad(self.bundle(), "sur.txt")

    def test_v4_existing_output_is_bad_and_unchanged(self):
        self.put("a.txt", b"a\n")
        self.listing("a.txt\n")
        with open(self.output, "wb") as handle:
            handle.write(b"keep me")
        result = self.bundle()
        self.assertEqual(result.returncode, 2, result)
        self.assertEqual(result.stdout, b"")
        self.assertTrue(result.stderr.startswith(ERROR_PREFIX))
        self.assertEqual(self.output_bytes(), b"keep me")

    def test_v4_existing_folder_or_dangling_link_as_output(self):
        self.put("a.txt", b"a\n")
        self.listing("a.txt\n")
        os.mkdir(self.output)
        self.assertEqual(self.bundle().returncode, 2)
        os.rmdir(self.output)
        os.symlink(os.path.join(self.base, "nowhere"), self.output)
        self.assertEqual(self.bundle().returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.base, "nowhere")))

    def test_v4_output_that_is_a_listed_file(self):
        path = self.put("a.txt", b"a\n")
        self.listing("a.txt\n")
        result = self.run_program(self.root, self.list_path, path)
        self.assertEqual(result.returncode, 2, result)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"a\n")


class TestExtra(Case):
    def test_extra_no_arguments_and_wrong_counts(self):
        for args in ((), (self.root,), (self.root, self.list_path), (self.root, self.list_path, self.output, "x")):
            with self.subTest(args=args):
                result = self.run_program(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"bundle: usage: python bundle.py ROOT LIST OUTPUT\n")

    def test_extra_list_comments_blanks_bom_and_crlf(self):
        self.put("a.txt", b"a\n")
        self.put("b.txt", b"b\n")
        self.listing(b"\xef\xbb\xbf# a comment\r\n\r\n   \r\na.txt\r\n# a.txt again\r\n\r\nb.txt")
        result = self.bundle()
        self.assertEqual(result.returncode, 0, result)
        self.assertTrue(result.stdout.startswith(b"2 files, 4 bytes, written to "))
        text = self.output_bytes().decode("utf-8")
        self.assertIn("| 1 | a.txt |", text)
        self.assertIn("| 2 | b.txt |", text)

    def test_extra_list_with_no_path_is_bad(self):
        self.listing("# only a comment\n\n")
        self.assert_bad(self.bundle())

    def test_extra_list_not_utf8_or_missing(self):
        self.listing(b"a.txt\xff\n")
        self.assert_bad(self.bundle())
        os.unlink(self.list_path)
        self.assert_bad(self.bundle())

    def test_extra_root_missing_or_a_file(self):
        self.listing("a.txt\n")
        for root in (os.path.join(self.base, "nope"), self.list_path):
            with self.subTest(root=root):
                result = self.run_program(root, self.list_path, self.output)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(os.path.exists(self.output))

    def test_extra_root_may_be_a_link_to_a_folder(self):
        self.put("a.txt", b"a\n")
        self.listing("a.txt\n")
        alias = os.path.join(self.base, "alias")
        os.symlink(self.root, alias)
        result = self.run_program(alias, self.list_path, self.output)
        self.assertEqual(result.returncode, 0, result)

    def test_extra_nothing_is_written_when_one_file_is_bad(self):
        self.put("a.txt", b"a\n")
        self.listing("a.txt\nmissing.txt\n")
        self.assert_bad(self.bundle())

    def test_extra_file_text_is_kept_exactly(self):
        raw = b"one\r\ntwo\r\nno final newline"
        self.put("crlf.txt", raw)
        self.put("empty.txt", b"")
        self.listing("crlf.txt\nempty.txt\n")
        self.assertEqual(self.bundle().returncode, 0)
        text = self.output_bytes()
        self.assertIn(b"\n```\none\r\ntwo\r\nno final newline\n```\n", text)
        self.assertIn(b"\n```\n```\n", text)
        self.assertIn(("| 2 | empty.txt | 0 | %s |" % sha(b"")).encode("ascii"), text)
        self.assertIn(("| 1 | crlf.txt | %d | %s |" % (len(raw), sha(raw))).encode("ascii"), text)

    def test_extra_markdown_characters_and_line_breaks_in_a_path_are_bad(self):
        # Codex P1 on pull request 61: a name must not carry Markdown or a line break into the bundle.
        for name in ("a|b.txt", "a`b.txt", "a*b.txt", "a#b.txt", "a[b].txt", "a<b>.txt", "a b.txt", "a\rb.txt"):
            with self.subTest(name=name):
                self.listing(name + "\n")
                self.assert_bad(self.bundle(), "a path has a character that is not allowed")

    def test_extra_folder_parts_are_opened_without_following_links(self):
        # Codex P1 on pull request 61: every folder on the way is opened relative to the last, links refused.
        self.put("real/inner.txt", b"x\n")
        os.symlink(os.path.join(self.root, "real"), os.path.join(self.root, "alias"))
        self.listing("alias/inner.txt\n")
        self.assert_bad(self.bundle(), "a link is not allowed")
        os.remove(self.output) if os.path.exists(self.output) else None
        self.listing("real/inner.txt\n")
        self.assertEqual(self.bundle().returncode, 0)

    def test_extra_unicode_path_and_a_file_that_is_a_byte_order_mark_file(self):
        raw = b"\xef\xbb\xbfbom file\n"
        self.put("déjà.txt", raw)
        self.listing("déjà.txt\n")
        self.assertEqual(self.bundle().returncode, 0)
        self.assertIn(sha(raw).encode("ascii"), self.output_bytes())

    def test_extra_output_in_a_missing_folder_exits_1(self):
        self.put("a.txt", b"a\n")
        self.listing("a.txt\n")
        missing = os.path.join(self.base, "no", "such", "out.md")
        result = self.run_program(self.root, self.list_path, missing)
        self.assertEqual(result.returncode, 1, result)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"bundle: cannot write the output\n")

    def test_extra_output_may_be_inside_root_when_not_listed(self):
        self.put("a.txt", b"a\n")
        self.listing("a.txt\n")
        inside = os.path.join(self.root, "out.md")
        result = self.run_program(self.root, self.list_path, inside)
        self.assertEqual(result.returncode, 0, result)

    def test_extra_only_the_output_is_created(self):
        self.put("a.txt", b"a\n")
        self.listing("a.txt\n")
        before = sorted(os.listdir(self.base)) + sorted(os.listdir(self.root))
        self.assertEqual(self.bundle().returncode, 0)
        after = sorted(os.listdir(self.base)) + sorted(os.listdir(self.root))
        self.assertEqual(sorted(after), sorted(before + ["out.md"]))

    def test_extra_two_runs_give_the_same_bundle(self):
        self.put("a.txt", b"a\n")
        self.listing("a.txt\n")
        self.assertEqual(self.bundle().returncode, 0)
        first = self.output_bytes()
        os.unlink(self.output)
        self.assertEqual(self.bundle().returncode, 0)
        self.assertEqual(self.output_bytes(), first)

    def test_extra_works_under_a_relative_root(self):
        self.put("a.txt", b"a\n")
        self.listing("a.txt\n")
        result = subprocess.run(
            [sys.executable, PROGRAM, "root", "list.txt", "rel.md"],
            capture_output=True,
            cwd=self.base,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result)
        self.assertEqual(result.stdout, b"1 files, 2 bytes, written to rel.md\n")


if __name__ == "__main__":
    unittest.main()
