"""Pick the next build request from a repository's open issues.

Usage: python next_request.py ISSUES_FILE BRANCHES_FILE

ISSUES_FILE holds the JSON array GitHub's REST API returns for "list
repository issues"; BRANCHES_FILE holds the array it returns for "list
branches". The program writes the lowest eligible issue number, or NONE, and
a line feed to standard output and exits with status 0.

An issue is eligible when it is not a pull request, is open, was opened by
the repository owner, has a title that begins with "Build request: " followed
by at least one non-whitespace character, and has no branch named
req-<number> yet.

On bad input (wrong number of arguments, an unreadable file, content that is
not UTF-8 JSON, a top level that is not an array, or any invalid element) it
writes one line beginning "next_request: " to standard error, writes nothing
to standard output and exits with status 2.

The choice is made by the fixed rules below and by nothing else. The program
opens only the two named files, for reading, and never writes out any text
taken from them: its messages are fixed strings.
"""

import json
import os
import sys

TITLE_PREFIX = "Build request: "
BRANCH_PREFIX = "req-"
REQUIRED_TEXT_KEYS = ("title", "state", "author_association")

EXIT_OK = 0
EXIT_OUTPUT_FAILED = 1
EXIT_BAD_INPUT = 2

STDOUT = 1
STDERR = 2


class BadInput(Exception):
    """Carries a fixed one-line reason, never text read from a file."""


def _reject_constant(_name):
    # NaN, Infinity and -Infinity are accepted by the json module but are not JSON.
    raise ValueError("not a JSON value")


def _object_with_unique_keys(pairs):
    # A repeated key would make "the state" or "the number" of an element
    # ambiguous, so such content is refused rather than silently resolved.
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("repeated key")
        result[key] = value
    return result


def load_array(path, label):
    """Return the JSON array held in the file at path, or raise BadInput."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except (OSError, ValueError, MemoryError):
        raise BadInput("cannot read the %s file" % label) from None
    try:
        # Strict UTF-8, no byte order mark, standard JSON only.
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_object_with_unique_keys,
        )
    except ValueError:
        raise BadInput("the %s file is not UTF-8 JSON" % label) from None
    except (RecursionError, MemoryError):
        # Not a verdict on the content: this program could not hold it.
        raise BadInput("the %s file is too deeply nested or too large to read" % label) from None
    if type(value) is not list:
        raise BadInput("the %s file does not hold a JSON array" % label)
    return value


def is_valid_issue(item):
    if type(item) is not dict:
        return False
    number = item.get("number")
    # type() rather than isinstance(): true and false are not integers here.
    if type(number) is not int or number < 1:
        return False
    return all(type(item.get(key)) is str for key in REQUIRED_TEXT_KEYS)


def is_valid_branch(item):
    return type(item) is dict and type(item.get("name")) is str


def is_eligible(item, branch_names):
    """Apply rules (a) to (e) to one valid issue element."""
    if "pull_request" in item:
        return False
    if item["state"] != "open":
        return False
    if item["author_association"] != "OWNER":
        return False
    title = item["title"]
    if not title.startswith(TITLE_PREFIX):
        return False
    if not title[len(TITLE_PREFIX):].strip():
        return False
    return BRANCH_PREFIX + str(item["number"]) not in branch_names


def pick(issues, branches):
    """Return the lowest eligible issue number, or None.

    Both lists are validated in full before anything is chosen.
    """
    for position, item in enumerate(issues):
        if not is_valid_issue(item):
            raise BadInput("element %d of the issues file is not a valid issue" % position)
    for position, item in enumerate(branches):
        if not is_valid_branch(item):
            raise BadInput("element %d of the branches file is not a valid branch" % position)
    branch_names = {item["name"] for item in branches}
    eligible = [item["number"] for item in issues if is_eligible(item, branch_names)]
    return min(eligible) if eligible else None


def _write(descriptor, text):
    # Exact bytes, written at once: no newline translation and nothing left
    # in a buffer to fail after the exit status has been decided.
    data = text.encode("ascii")
    while data:
        data = data[os.write(descriptor, data):]


def _report(reason):
    try:
        _write(STDERR, "next_request: %s\n" % reason)
    except OSError:
        pass


def main(argv):
    # An issue number is "an integer of 1 or more" with no upper bound, so the
    # interpreter's default cap on the length of an integer's text is lifted.
    sys.set_int_max_str_digits(0)
    try:
        if len(argv) != 3:
            raise BadInput("expected exactly two arguments: ISSUES_FILE BRANCHES_FILE")
        issues = load_array(argv[1], "issues")
        branches = load_array(argv[2], "branches")
        number = pick(issues, branches)
    except BadInput as problem:
        _report(str(problem))
        return EXIT_BAD_INPUT
    answer = "NONE" if number is None else str(number)
    try:
        _write(STDOUT, answer + "\n")
    except OSError:
        _report("cannot write the result")
        return EXIT_OUTPUT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
