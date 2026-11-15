"""List the test files that mention the files or names a change will touch.

Usage: python affected_tests.py ROOT TARGETS_FILE

It only reads files. It never runs tests and never uses the network.
"""
import fnmatch
import os
import posixpath
import re
import stat
import sys

PREFIX = "affected_tests: "
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
TEST_PATTERNS = (
    "test_*.py",
    "*_test.py",
    "*.test.ts",
    "*.test.tsx",
    "*.test.js",
    "*.spec.ts",
)
SKIPPED_DIRECTORIES = (".git", "node_modules")


class BadInput(Exception):
    """The command line or the targets file is unusable (exit status 2)."""


def parse_targets(text):
    """Return the validated targets of the targets file text, in order."""
    targets = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "/" in line:
            if line.startswith("/") or "\\" in line:
                raise BadInput("invalid target path")
            if any(segment in ("", ".", "..") for segment in line.split("/")):
                raise BadInput("invalid target path")
        elif not NAME_RE.fullmatch(line):
            raise BadInput("invalid target name")
        targets.append(line)
    if not targets:
        raise BadInput("no targets")
    return targets


def search_term(target):
    """Return the search term of a target (S2)."""
    if "/" not in target:
        return target
    return posixpath.splitext(target.rsplit("/", 1)[1])[0]


def term_pattern(term):
    return re.compile(
        "(?<![A-Za-z0-9_])" + re.escape(term) + "(?![A-Za-z0-9_])"
    )


def is_test_name(name):
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in TEST_PATTERNS)


def find_test_files(root):
    """Return the paths, relative to root with forward slashes, of the test
    files under root. Symbolic links are not followed."""
    found = []
    for directory, subdirectories, names in os.walk(root, followlinks=False):
        subdirectories[:] = [
            d for d in subdirectories if d not in SKIPPED_DIRECTORIES
        ]
        relative = os.path.relpath(directory, root)
        for name in names:
            if not is_test_name(name):
                continue
            full = os.path.join(directory, name)
            try:
                if not stat.S_ISREG(os.lstat(full).st_mode):
                    continue
            except OSError:
                continue
            if relative == os.curdir:
                path = name
            else:
                path = "/".join(relative.split(os.sep) + [name])
            found.append((path, full))
    return found


def affected(root, targets):
    patterns = [term_pattern(t) for t in {search_term(x) for x in targets}]
    target_paths = {t for t in targets if "/" in t}
    result = []
    for path, full in find_test_files(root):
        if path in target_paths:
            result.append(path)
            continue
        try:
            with open(full, "rb") as handle:
                text = handle.read().decode("utf-8", "replace")
        except OSError:
            continue
        if any(p.search(text) for p in patterns):
            result.append(path)
    return sorted(result)


def read_targets(path):
    try:
        with open(path, "rb") as handle:
            return handle.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise BadInput("cannot read targets file")


def write_all(data):
    """Write data to standard output; return False if that is not possible."""
    if sys.stdout is None:
        return False
    # Write through the unbuffered layer so that nothing is left in a buffer
    # for the interpreter to flush (and fail on) at exit.
    stream = sys.stdout.buffer
    stream = getattr(stream, "raw", stream)
    view = memoryview(data)
    try:
        while view:
            written = stream.write(view)
            if not written:
                return False
            view = view[written:]
    except (OSError, ValueError):
        return False
    return True


def fail(message, status):
    try:
        sys.stderr.write(PREFIX + message + "\n")
        sys.stderr.flush()
    except (OSError, ValueError, AttributeError):
        pass
    return status


def run(arguments):
    if len(arguments) != 2:
        raise BadInput("usage: affected_tests.py ROOT TARGETS_FILE")
    root, targets_file = arguments
    if not os.path.isdir(root):
        raise BadInput("ROOT is not a directory")
    targets = parse_targets(read_targets(targets_file))
    paths = affected(root, targets)
    lines = "".join(p + "\n" for p in paths) if paths else "NONE\n"
    return lines.encode("utf-8", "surrogateescape")


def main():
    try:
        output = run(sys.argv[1:])
    except BadInput as problem:
        return fail(str(problem), 2)
    except Exception:
        return fail("unexpected error", 1)
    if not write_all(output):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
