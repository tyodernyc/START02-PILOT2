import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "affected_tests.py")


class Workspace:
    """A temporary ROOT folder and a targets file kept outside it."""

    def __init__(self, test):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "root")
        os.mkdir(self.root)
        self.targets_file = os.path.join(self.tmp.name, "targets.txt")

    def add(self, relative, content="", binary=False):
        path = os.path.join(self.root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if isinstance(content, str):
            content = content.encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def run(self, targets, raw=None):
        if raw is None:
            raw = targets.encode("utf-8")
        with open(self.targets_file, "wb") as handle:
            handle.write(raw)
        return run_program(self.root, self.targets_file)


def run_program(*args, **options):
    return subprocess.run(
        [sys.executable, PROGRAM, *args],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        **options,
    )


class AffectedTestsBase(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(self)

    def assertListed(self, result, expected_lines):
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout, "".join(line + "\n" for line in expected_lines).encode()
        )

    def assertBadInput(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        lines = result.stderr.decode("utf-8").split("\n")
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1], "")
        self.assertTrue(lines[0].startswith("affected_tests: "))
        self.assertNotIn(b"Traceback", result.stderr)


class TestChecks(AffectedTestsBase):
    # V1
    def test_v1_import_in_test_file(self):
        self.ws.add("src/foo.py", "x = 1\n")
        self.ws.add("tests/test_foo.py", "import foo\n")
        self.assertListed(self.ws.run("src/foo.py\n"), ["tests/test_foo.py"])

    # V2
    def test_v2_whole_word_rule(self):
        self.ws.add("tests/test_a.py", "foobar\n")
        self.ws.add("tests/test_b.py", "my_foo\n")
        self.ws.add("tests/test_c.py", "foo.bar\n")
        self.ws.add("tests/test_d.py", 'x = "foo"\n')
        self.ws.add("tests/test_e.py", "foo")
        self.ws.add("tests/test_f.py", "1foo\n")
        self.assertListed(
            self.ws.run("src/foo.py\n"),
            ["tests/test_c.py", "tests/test_d.py", "tests/test_e.py"],
        )

    # V3
    def test_v3_name_target_and_non_test_file(self):
        self.ws.add("a/x.test.ts", "assign_bucket(1)\n")
        self.ws.add("b/y.ts", "assign_bucket(1)\n")
        self.assertListed(self.ws.run("assign_bucket\n"), ["a/x.test.ts"])

    def test_v3_stem_of_path_target(self):
        self.ws.add("t/a.test.ts", "step20_assign_bucket\n")
        self.ws.add("t/b.test.ts", "step20_assign_bucket2\n")
        self.assertListed(
            self.ws.run("apps/x/step20_assign_bucket.ts\n"), ["t/a.test.ts"]
        )

    def test_v3_stem_keeps_inner_dots_and_no_extension(self):
        self.ws.add("t/a.test.ts", "see b.test here\n")
        self.ws.add("t/test_m.py", "run Makefile now\n")
        self.ws.add("t/test_n.py", "b only\n")
        self.assertListed(self.ws.run("a/b.test.ts\n"), ["t/a.test.ts"])
        self.assertListed(self.ws.run("a/Makefile\n"), ["t/test_m.py"])

    def test_all_test_file_name_patterns(self):
        names = [
            "test_one.py",
            "two_test.py",
            "three.test.ts",
            "four.test.tsx",
            "five.test.js",
            "six.spec.ts",
        ]
        for name in names:
            self.ws.add("d/" + name, "needle\n")
        for name in ["seven.spec.js", "eight.py", "Test_nine.py", "ten.test.py"]:
            self.ws.add("d/" + name, "needle\n")
        self.assertListed(
            self.ws.run("needle\n"), sorted("d/" + name for name in names)
        )

    # V4
    def test_v4_skipped_directories(self):
        self.ws.add("node_modules/pkg/test_foo.py", "foo\n")
        self.ws.add("a/node_modules/x.test.js", "foo\n")
        self.ws.add(".git/test_foo.py", "foo\n")
        self.ws.add("a/.git/hooks/y_test.py", "foo\n")
        self.assertListed(self.ws.run("foo\n"), ["NONE"])

    # V5
    def test_v5_sorted_nested_relative_forward_slashes(self):
        self.ws.add("z/test_a.py", "foo\n")
        self.ws.add("a/b/c/d_test.py", "foo\n")
        self.ws.add("a/test_x.py", "foo\n")
        self.ws.add("test_top.py", "foo\n")
        self.ws.add("a-b/test_y.py", "foo\n")
        self.assertListed(
            self.ws.run("foo\n"),
            sorted(
                [
                    "z/test_a.py",
                    "a/b/c/d_test.py",
                    "a/test_x.py",
                    "test_top.py",
                    "a-b/test_y.py",
                ]
            ),
        )
        # plain string order: "-" (45) sorts before "/" (47)
        result = self.ws.run("foo\n")
        lines = result.stdout.decode().split("\n")[:-1]
        self.assertEqual(lines, sorted(lines))
        self.assertLess(lines.index("a-b/test_y.py"), lines.index("a/b/c/d_test.py"))

    # V6
    def test_v6_target_that_is_a_test_file(self):
        self.ws.add("tests/test_bar.py", "nothing relevant\n")
        self.ws.add("tests/test_other.py", "nothing relevant\n")
        self.assertListed(self.ws.run("tests/test_bar.py\n"), ["tests/test_bar.py"])

    def test_v6_missing_target_path_is_allowed(self):
        self.ws.add("tests/test_other.py", "nothing\n")
        self.assertListed(self.ws.run("src/missing.py\n"), ["NONE"])

    # V7
    def test_v7_none(self):
        self.ws.add("tests/test_foo.py", "import something_else\n")
        self.assertListed(self.ws.run("src/foo.py\n"), ["NONE"])

    def test_v7_empty_root(self):
        self.assertListed(self.ws.run("foo\n"), ["NONE"])

    # V8
    def test_v8_invalid_utf8_in_test_file(self):
        self.ws.add("tests/test_foo.py", b"\xff\xfe import foo \x80\x81\n")
        self.ws.add("tests/test_bar.py", b"\xff\xfe nothing \x80\x81\n")
        self.assertListed(self.ws.run("src/foo.py\n"), ["tests/test_foo.py"])

    # V9
    def test_v9_no_arguments(self):
        self.assertBadInput(run_program())

    def test_v9_one_argument(self):
        self.assertBadInput(run_program(self.ws.root))

    def test_v9_three_arguments(self):
        self.ws.run("foo\n")
        self.assertBadInput(run_program(self.ws.root, self.ws.targets_file, "x"))

    def test_v9_root_is_a_file(self):
        path = self.ws.add("file.txt", "x")
        with open(self.ws.targets_file, "w") as handle:
            handle.write("foo\n")
        self.assertBadInput(run_program(path, self.ws.targets_file))

    def test_v9_root_missing(self):
        with open(self.ws.targets_file, "w") as handle:
            handle.write("foo\n")
        self.assertBadInput(
            run_program(os.path.join(self.ws.root, "nope"), self.ws.targets_file)
        )

    def test_v9_targets_file_missing(self):
        self.assertBadInput(
            run_program(self.ws.root, os.path.join(self.ws.tmp.name, "nope.txt"))
        )

    def test_v9_targets_file_is_a_directory(self):
        self.assertBadInput(run_program(self.ws.root, self.ws.root))

    def test_v9_targets_file_not_utf8(self):
        self.assertBadInput(self.ws.run(None, raw=b"foo\n\xff\xfe\n"))

    def test_v9_only_blank_and_comment_lines(self):
        self.assertBadInput(self.ws.run("\n   \n# a comment\n\t# another\n\n"))
        self.assertBadInput(self.ws.run(""))

    def test_v9_bad_targets(self):
        for bad in [
            "../x.py",
            "/abs.py",
            "bad-name",
            "a/../x.py",
            "a/./x.py",
            "a//x.py",
            "a/b/",
            "a\\b.py",
            "a/b\\c.py",
            "1abc",
            "foo bar",
            "naïve",
        ]:
            with self.subTest(target=bad):
                self.assertBadInput(self.ws.run("good_name\n" + bad + "\n"))

    def test_v9_nothing_printed_when_one_target_is_bad(self):
        self.ws.add("tests/test_foo.py", "foo\n")
        result = self.ws.run("foo\nbad-name\n")
        self.assertBadInput(result)


class TestRules(AffectedTestsBase):
    def test_blank_lines_comments_and_whitespace(self):
        self.ws.add("tests/test_foo.py", "foo\n")
        self.ws.add("tests/test_baz.py", "baz\n")
        text = "\n# comment\n   \n  foo  \r\n\t# not a target bar-baz\n"
        self.assertListed(self.ws.run(text), ["tests/test_foo.py"])
        self.assertListed(
            self.ws.run("  src/baz.py \n"), ["tests/test_baz.py"]
        )

    def test_hash_inside_a_line_is_not_a_comment(self):
        self.assertBadInput(self.ws.run("foo # note\n"))

    def test_symbolic_links_not_followed(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        with open(os.path.join(outside.name, "test_x.py"), "w") as handle:
            handle.write("foo\n")
        real = self.ws.add("real/test_real.py", "foo\n")
        try:
            os.symlink(outside.name, os.path.join(self.ws.root, "linkdir"))
            os.symlink(real, os.path.join(self.ws.root, "test_link.py"))
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links not available")
        self.assertListed(self.ws.run("foo\n"), ["real/test_real.py"])

    def test_directory_named_like_a_test_file_is_not_listed(self):
        os.makedirs(os.path.join(self.ws.root, "test_dir.py"))
        self.ws.add("test_dir.py/inner.txt", "foo\n")
        self.assertListed(self.ws.run("foo\n"), ["NONE"])

    def test_target_path_is_matched_exactly_and_case_sensitively(self):
        self.ws.add("tests/test_bar.py", "nothing\n")
        self.assertListed(self.ws.run("Tests/test_bar.py\n"), ["NONE"])

    def test_case_sensitive_terms(self):
        self.ws.add("tests/test_a.py", "FOO\n")
        self.assertListed(self.ws.run("foo\n"), ["NONE"])

    def test_term_at_start_and_end_of_file_and_next_to_punctuation(self):
        self.ws.add("t/test_a.py", "foo")
        self.ws.add("t/test_b.py", "(foo)")
        self.ws.add("t/test_c.py", "foo_")
        self.ws.add("t/test_d.py", "_foo")
        self.ws.add("t/test_e.py", "foo9")
        self.assertListed(self.ws.run("foo\n"), ["t/test_a.py", "t/test_b.py"])

    def test_first_mention_is_part_of_a_word_second_is_whole(self):
        self.ws.add("t/test_a.py", "foobar and then foo\n")
        self.assertListed(self.ws.run("foo\n"), ["t/test_a.py"])

    def test_dotfile_target_has_a_non_empty_term(self):
        self.ws.add("t/test_a.py", "nothing here\n")
        self.assertListed(self.ws.run("conf/.env\n"), ["NONE"])

    def test_several_targets(self):
        self.ws.add("t/test_a.py", "alpha\n")
        self.ws.add("t/test_b.py", "beta\n")
        self.ws.add("t/test_c.py", "gamma\n")
        self.assertListed(
            self.ws.run("alpha\nsrc/beta.py\nalpha\n"),
            ["t/test_a.py", "t/test_b.py"],
        )

    def test_unreadable_test_file_is_skipped(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("permissions are not enforced for this user")
        path = self.ws.add("t/test_a.py", "foo\n")
        self.ws.add("t/test_b.py", "foo\n")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        self.assertListed(self.ws.run("foo\n"), ["t/test_b.py"])

    def test_root_may_be_given_with_trailing_slash_or_dot_path(self):
        self.ws.add("t/test_a.py", "foo\n")
        with open(self.ws.targets_file, "w") as handle:
            handle.write("foo\n")
        for root in (self.ws.root + "/", os.path.join(self.ws.root, "t", "..")):
            result = run_program(root, self.ws.targets_file)
            self.assertListed(result, ["t/test_a.py"])

    def test_unwritable_output_gives_status_1(self):
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full not available")
        self.ws.add("t/test_a.py", "foo\n")
        with open(self.ws.targets_file, "w") as handle:
            handle.write("foo\n")
        with open("/dev/full", "wb") as full:
            result = subprocess.run(
                [sys.executable, PROGRAM, self.ws.root, self.ws.targets_file],
                stdout=full,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_closed_standard_output_gives_status_1(self):
        if os.name != "posix":
            self.skipTest("needs POSIX file descriptors")
        self.ws.add("t/test_a.py", "foo\n")
        with open(self.ws.targets_file, "w") as handle:
            handle.write("foo\n")
        result = subprocess.run(
            [sys.executable, PROGRAM, self.ws.root, self.ws.targets_file],
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            preexec_fn=lambda: os.close(1),
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b"Traceback", result.stderr)



class TestHardening(AffectedTestsBase):
    """Build request #44: F3 (unwritable standard error or output) and F4
    (targets at the repository root)."""

    def test_f3_unwritable_standard_error_still_gives_status_2(self):
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full not available")
        with open("/dev/full", "wb") as full:
            result = subprocess.run(
                [sys.executable, PROGRAM],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=full,
            )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")

    def test_f3_unwritable_standard_error_with_bad_target(self):
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full not available")
        with open(self.ws.targets_file, "w") as handle:
            handle.write("bad-name\n")
        with open("/dev/full", "wb") as full:
            result = subprocess.run(
                [sys.executable, PROGRAM, self.ws.root, self.ws.targets_file],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=full,
            )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")

    def test_f3_unwritable_standard_output_gives_status_1(self):
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full not available")
        self.ws.add("test_a.py", "import attention\n")
        with open(self.ws.targets_file, "w") as handle:
            handle.write("attention.py\n")
        with open("/dev/full", "wb") as full:
            result = subprocess.run(
                [sys.executable, PROGRAM, self.ws.root, self.ws.targets_file],
                stdin=subprocess.DEVNULL,
                stdout=full,
                stderr=subprocess.PIPE,
            )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_f4_root_level_file_is_a_path_with_the_term_of_its_stem(self):
        self.ws.add("test_a.py", "import attention\n")
        self.ws.add("test_b.py", "import attention_extra\n")
        self.ws.add("tests/test_c.py", "from attention import main\n")
        self.assertListed(
            self.ws.run("attention.py\n"), ["test_a.py", "tests/test_c.py"]
        )

    def test_f4_root_level_test_file_target_is_listed_without_a_mention(self):
        self.ws.add("test_a.py", "nothing here\n")
        self.ws.add("test_b.py", "nothing here\n")
        self.assertListed(self.ws.run("test_a.py\n"), ["test_a.py"])

    def test_f4_dot_segments_are_still_rejected(self):
        for bad in ("./x.py", "../x.py", "./attention.py", ".", ".."):
            with self.subTest(target=bad):
                self.assertBadInput(self.ws.run(bad + "\n"))

    def test_f4_bad_name_is_still_rejected(self):
        self.assertBadInput(self.ws.run("bad-name\n"))

    def test_f4_name_without_slash_or_dot_is_still_a_name(self):
        self.ws.add("test_a.py", "uses foo here\n")
        self.ws.add("test_b.py", "uses foobar here\n")
        self.assertListed(self.ws.run("foo\n"), ["test_a.py"])

    def test_f4_dotted_root_level_target_is_checked_as_a_path(self):
        self.assertBadInput(self.ws.run("a\\b.py\n"))
        self.ws.add("test_a.py", "run archive.tar now\n")
        self.assertListed(self.ws.run("archive.tar.gz\n"), ["test_a.py"])


if __name__ == "__main__":
    unittest.main()
