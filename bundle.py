"""Pack a list of text files into one Markdown file with a SHA-256 manifest (build request #60).

Usage: python bundle.py ROOT LIST OUTPUT

LIST is a UTF-8 text file with one path per line, relative to ROOT. The program
reads only the files LIST names (under ROOT) and writes only OUTPUT, a Markdown
file for an outside reviewer: a manifest of SHA-256 hashes of the exact bytes of
each file, then each file's text in a fenced block that its own content cannot
close. It does no network access.

The rules for LIST, the files and OUTPUT are in build request #60. Where that
request is silent, the pull request body lists each choice under "Assumptions".
Exit status: 0 success, 1 the output could not be written, 2 bad input.
Runs on Python 3.13; standard library only.
"""

import hashlib
import os
import re
import stat
import sys

PREFIX = "bundle: "
USAGE = "usage: python bundle.py ROOT LIST OUTPUT"
BOM = "﻿"
BACKTICKS = re.compile(r"`+")


class BadInput(Exception):
    """The input is wrong; the message is a fixed string (naming the path where one is at fault)."""


class WriteFailed(Exception):
    """The output could not be written."""


def read_list(path):
    """Return the listed paths, in order, after the rules for LIST have been applied."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        raise BadInput("cannot read the list file")
    try:
        text = raw.decode("utf-8")
    except ValueError:
        raise BadInput("the list file is not UTF-8")
    if text.startswith(BOM):
        text = text[1:]
    paths = []
    for line in text.split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        if line.strip() == "" or line.startswith("#"):
            continue
        check_path(line)
        if line in paths:
            raise BadInput("a path is listed more than once: " + line)
        paths.append(line)
    if not paths:
        raise BadInput("the list file names no path")
    return paths


def check_path(path):
    """A listed path must be relative, use /, and have no empty, . or .. part."""
    if path != path.strip():
        raise BadInput("a path has a space around it: " + path)
    if "\x00" in path or "\\" in path:
        raise BadInput("a path has a character that is not allowed: " + path)
    if path.startswith("/"):
        raise BadInput("a path must be relative: " + path)
    for part in path.split("/"):
        if part == "":
            raise BadInput("a path has an empty part: " + path)
        if part in (".", ".."):
            raise BadInput("a path has a . or .. part: " + path)


def read_member(root, real_root, path):
    """Return the exact bytes of the listed file; raise BadInput naming the path if it is not usable."""
    problem = "not a regular file inside ROOT: " + path
    current = root
    try:
        for part in path.split("/"):
            current = os.path.join(current, part)
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise BadInput("a link is not allowed: " + path)
        if not stat.S_ISREG(os.lstat(current).st_mode):
            raise BadInput(problem)
        real = os.path.realpath(current)
        if os.path.commonpath([real, real_root]) != real_root or real == real_root:
            raise BadInput(problem)
        descriptor = os.open(current, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise BadInput(problem)
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read()
        finally:
            os.close(descriptor)
    except BadInput:
        raise
    except (OSError, ValueError):
        raise BadInput("cannot read the file: " + path)
    try:
        raw.decode("utf-8")
    except ValueError:
        raise BadInput("the file is not UTF-8: " + path)
    return raw


def fence_for(text):
    """Backticks, at least three and one more than the longest run inside the text."""
    longest = max((len(run) for run in BACKTICKS.findall(text)), default=0)
    return "`" * max(3, longest + 1)


def cell(text):
    """A path in a table cell: a vertical bar would end the cell early."""
    return text.replace("|", "\\|")


def render(paths, members):
    """The text of OUTPUT. The file text is kept exactly as it is, so the hashes can be checked."""
    hashes = [hashlib.sha256(raw).hexdigest() for raw in members]
    out = ["# Bundle\n", "Files: %d\n" % len(paths), "\n"]
    out.append("| # | Path | Bytes | SHA-256 |\n")
    out.append("| --- | --- | --- | --- |\n")
    for number, (path, raw, digest) in enumerate(zip(paths, members, hashes), 1):
        out.append("| %d | %s | %d | %s |\n" % (number, cell(path), len(raw), digest))
    for number, (path, raw, digest) in enumerate(zip(paths, members, hashes), 1):
        text = raw.decode("utf-8")
        fence = fence_for(text)
        out.append("\n## %d. %s\n" % (number, path))
        out.append("SHA-256: %s\n\n" % digest)
        out.append(fence + "\n")
        out.append(text if text == "" or text.endswith("\n") else text + "\n")
        out.append(fence + "\n")
    return "".join(out)


def check_output(output, root, paths):
    """OUTPUT must not exist, and must not be one of the listed files."""
    if os.path.lexists(output):
        raise BadInput("the output already exists")
    target = os.path.realpath(output)
    for path in paths:
        if os.path.realpath(os.path.join(root, path)) == target:
            raise BadInput("the output is one of the listed files")


def write_output(output, text):
    """Create OUTPUT (it must not exist) and write the text as UTF-8 with no line-ending change."""
    data = text.encode("utf-8")
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        raise BadInput("the output already exists")
    except OSError:
        raise WriteFailed()
    try:
        view = memoryview(data)
        while len(view):
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("nothing was written")
            view = view[written:]
    except OSError:
        os.close(descriptor)
        try:
            os.unlink(output)
        except OSError:
            pass
        raise WriteFailed()
    try:
        os.close(descriptor)
    except OSError:
        try:
            os.unlink(output)
        except OSError:
            pass
        raise WriteFailed()


def write_fd(descriptor, text, errors="replace"):
    """Write the text to a file descriptor with os.write.

    Nothing is left in a buffer, so Python's shutdown flush cannot fail after
    the exit status has been decided (it would turn the status into 120).
    """
    view = memoryview(text.encode("utf-8", errors))
    while len(view):
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("nothing was written")
        view = view[written:]


def fail(code, message):
    try:
        write_fd(2, PREFIX + message + "\n")
    except Exception:
        pass
    return code


def write_result(line):
    """Write the line to standard output; return True on success."""
    try:
        write_fd(1, line + "\n", "strict")
        return True
    except Exception:
        return False


def main(argv):
    if len(argv) != 4:
        return fail(2, USAGE)
    root, list_path, output = argv[1], argv[2], argv[3]
    try:
        if not os.path.isdir(root):
            raise BadInput("ROOT is not a folder")
        real_root = os.path.realpath(root)
        paths = read_list(list_path)
        members = [read_member(root, real_root, path) for path in paths]
        check_output(output, root, paths)
        write_output(output, render(paths, members))
    except BadInput as error:
        return fail(2, str(error))
    except (WriteFailed, MemoryError):
        return fail(1, "cannot write the output")
    total = sum(len(raw) for raw in members)
    if not write_result("%d files, %d bytes, written to %s" % (len(paths), total, output)):
        return fail(1, "cannot write the result")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
