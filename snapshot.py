"""Build the one JSON snapshot that merge_check.py reads (build request #54).

Usage: python snapshot.py PULL FILES CHECKS ISSUE_COMMENTS REVIEW_COMMENTS ALLOWED
           [--required-checks NAME,NAME] [--protected PREFIX,PREFIX]

The coordinator saves the pull request, its changed files, the check runs of
its head commit, its issue comments and its review comments with `gh api`,
and keeps the allowed path patterns in a text file. This program joins them
into the one JSON object that `python merge_check.py SNAPSHOT_FILE` reads and
writes that object to standard output. It does no network access and opens
only the files named on its command line, for reading.

PULL            the JSON object from GET /repos/{o}/{r}/pulls/{n}.
FILES,
ISSUE_COMMENTS,
REVIEW_COMMENTS either a JSON array (one page) or a JSON array of arrays (what
                `gh api --paginate --slurp` writes); arrays of arrays are
                joined in order.
CHECKS          the JSON object from GET /repos/{o}/{r}/commits/{sha}/check-runs,
                or an array of such objects (pages); the check_runs lists are
                joined in order and total_count is taken from the first page.
ALLOWED         a UTF-8 text file with one allowed path pattern per line;
                blank lines and lines starting with # are ignored.

Input holding NaN, Infinity or -Infinity (not JSON), or a number too large for a
float (such as 1e999), is bad input.
Exit status: 0 success, 1 the result could not be written, 2 bad input.
Runs on Python 3.8 or later; standard library only.
"""

import json
import os
import sys

PREFIX = "snapshot: "
USAGE = (
    "usage: python snapshot.py PULL FILES CHECKS ISSUE_COMMENTS REVIEW_COMMENTS ALLOWED"
    " [--required-checks NAME,NAME] [--protected PREFIX,PREFIX]"
)
POSITIONAL = ("PULL", "FILES", "CHECKS", "ISSUE_COMMENTS", "REVIEW_COMMENTS", "ALLOWED")
OPTIONS = ("--required-checks", "--protected")
TRUNCATED_AT = 3000  # GitHub's limit for the list of files of a pull request


class BadInput(Exception):
    """The input is wrong; the message is a fixed string naming the argument."""


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def read_bytes(name, path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        raise BadInput("cannot read " + name)


def decode(name, raw):
    try:
        return raw.decode("utf-8")
    except ValueError:
        raise BadInput(name + " is not UTF-8")


def load_json(name, path):
    """Read the file as UTF-8 JSON; NaN, Infinity and -Infinity are refused."""

    def reject_constant(constant):
        raise BadInput(name + " holds " + constant + ", which is not JSON")

    def parse_float(text):
        """A number such as 1e999 is JSON, but Python reads it as infinity."""
        value = float(text)
        if value in (float("inf"), float("-inf")):
            raise BadInput(name + " holds a number too large for JSON")
        return value

    text = decode(name, read_bytes(name, path))
    try:
        return json.loads(text, parse_constant=reject_constant, parse_float=parse_float)
    except (ValueError, RecursionError, MemoryError):
        raise BadInput(name + " is not UTF-8 JSON")


def read_object(name, path):
    value = load_json(name, path)
    if not isinstance(value, dict):
        raise BadInput(name + " must be a JSON object")
    return value


def all_objects(items):
    return all(isinstance(item, dict) for item in items)


def read_list(name, path):
    """One page (a list of objects) or a list of pages; return the joined list."""
    message = name + " must be a JSON array of objects or an array of such arrays"
    value = load_json(name, path)
    if not isinstance(value, list):
        raise BadInput(message)
    if all(isinstance(item, list) for item in value):
        joined = []
        for page in value:
            if not all_objects(page):
                raise BadInput(message)
            joined.extend(page)
        return joined
    if not all_objects(value):
        raise BadInput(message)
    return value


def read_checks(name, path):
    """The check-runs object, or a list of such objects; return the joined object."""
    message = name + " must be a check-runs JSON object or an array of such objects"
    value = load_json(name, path)
    if isinstance(value, dict):
        pages = [value]
    elif isinstance(value, list) and len(value) > 0 and all_objects(value):
        pages = value
    else:
        raise BadInput(message)
    runs = []
    for page in pages:
        page_runs = page.get("check_runs")
        if not isinstance(page_runs, list) or not all_objects(page_runs):
            raise BadInput(message)
        runs.extend(page_runs)
    joined = {}
    if "total_count" in pages[0]:
        total = pages[0]["total_count"]
        if total is not None and not is_int(total):
            raise BadInput(message)
        joined["total_count"] = total
    joined["check_runs"] = runs
    return joined


def read_allowed(name, path):
    text = decode(name, read_bytes(name, path))
    if text.startswith("\ufeff"):
        text = text[1:]
    patterns = []
    for line in text.splitlines():
        line = line.strip()
        if line == "" or line.startswith("#"):
            continue
        patterns.append(line)
    if not patterns:
        raise BadInput(name + " holds no path pattern")
    return patterns


def read_names(name, value):
    """A comma-separated list of distinct, non-empty names with no spaces around them."""
    names = value.split(",")
    if any(item == "" for item in names):
        raise BadInput(name + " must be a comma-separated list of non-empty names")
    if any(item != item.strip() for item in names):
        raise BadInput(name + " must not have spaces around a name")
    if len(set(names)) != len(names):
        raise BadInput(name + " must not repeat a name")
    return names


def parse_arguments(argv):
    """Return (positional values in order, options); raise BadInput on a wrong command line."""
    positional = []
    options = {}
    index = 1
    while index < len(argv):
        token = argv[index]
        if token.startswith("--"):
            if token not in OPTIONS or token in options or index + 1 >= len(argv):
                raise BadInput(USAGE)
            options[token] = argv[index + 1]
            index += 2
        else:
            positional.append(token)
            index += 1
    if len(positional) != len(POSITIONAL):
        raise BadInput(USAGE)
    return positional, options


def build(argv):
    paths, options = parse_arguments(argv)
    pull_path, files_path, checks_path, issues_path, reviews_path, allowed_path = paths
    snapshot = {
        "pull": read_object("PULL", pull_path),
        "files": read_list("FILES", files_path),
        "check_runs": read_checks("CHECKS", checks_path),
        "issue_comments": read_list("ISSUE_COMMENTS", issues_path),
        "review_comments": read_list("REVIEW_COMMENTS", reviews_path),
        "allowed": read_allowed("ALLOWED", allowed_path),
    }
    if "--required-checks" in options:
        snapshot["required_checks"] = read_names("--required-checks", options["--required-checks"])
    if "--protected" in options:
        snapshot["protected"] = read_names("--protected", options["--protected"])
    if len(snapshot["files"]) >= TRUNCATED_AT:
        snapshot["files_truncated"] = True
    try:
        return json.dumps(snapshot, allow_nan=False)
    except (ValueError, RecursionError, MemoryError):
        raise BadInput("the input is too large or too deep")


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


def write_result(text):
    """Write the text to standard output; return True on success."""
    try:
        write_fd(1, text + "\n", "strict")
        return True
    except Exception:
        return False


def main(argv):
    # A valid JSON integer may have any number of digits, so the interpreter's
    # cap on the length of an integer's text is lifted where it exists.
    if hasattr(sys, "set_int_max_str_digits"):
        sys.set_int_max_str_digits(0)
    try:
        text = build(argv)
    except BadInput as error:
        return fail(2, str(error))
    except (RecursionError, MemoryError):
        return fail(2, "the input is too large or too deep")
    if not write_result(text):
        return fail(1, "cannot write the snapshot")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
