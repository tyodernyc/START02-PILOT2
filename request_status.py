"""Report in one fixed line where a pull request stands.

Usage: python request_status.py PULL_FILE CHECKS_FILE

PULL_FILE holds the JSON object GitHub's REST API returns for "get a pull
request"; CHECKS_FILE holds the object it returns for "list check runs for a
Git reference" (keys total_count and check_runs). The program writes one of

    MERGED    CLOSED    DRAFT    READY    WAITING
    BLOCKED tests    BLOCKED review    BLOCKED tests review

and a line feed to standard output and exits with status 0.

Both files are validated in full first. Then, by the first rule that applies:
merged is true gives MERGED; state closed gives CLOSED; draft is true gives
DRAFT. Otherwise only the check runs on the pull request's head commit that
are named exactly "tests" or "review" are looked at, and for each of the two
names the run with the highest id is the one that counts. A counted run that
is completed without the conclusion success blocks; when both counted runs
are completed with success the answer is READY; anything else is WAITING.

On bad input (wrong number of arguments, an unreadable file, content that is
not UTF-8 JSON, or a pull request or check runs that are not valid) it writes
one line beginning "request_status: " to standard error, writes nothing to
standard output and exits with status 2. If the result cannot be written to
standard output it exits with status 1.

The line is a report only. It gives no permission: GitHub's ruleset still
decides whether a merge is possible. The answer comes from the fixed rules
below and from nothing else. The program opens only the two named files, for
reading, and never writes out any text taken from them or from its
arguments: every message is a fixed string.
"""

import json
import os
import sys

# The required checks, in the order in which failing ones are reported.
REQUIRED_CHECKS = ("tests", "review")

SHA_LENGTH = 40
SHA_CHARACTERS = frozenset("0123456789abcdef")

PASSED = "passed"
FAILED = "failed"
NOT_COMPLETED = "not completed"

EXIT_OK = 0
EXIT_OUTPUT_FAILED = 1
EXIT_BAD_INPUT = 2

STDOUT = 1
STDERR = 2

WRONG_ARGUMENTS = "expected exactly two arguments: PULL_FILE CHECKS_FILE"
CANNOT_WRITE = "cannot write the result"

# Every reason is spelled out in full here so that no message is ever
# assembled from anything but these fixed strings.
PULL_MESSAGES = {
    "unreadable": "cannot read the pull request file",
    "not json": "the pull request file is not UTF-8 JSON",
    "too large": "the pull request file is too deeply nested or too large to read",
    "not an object": "the pull request file does not hold a JSON object",
    "state": "the pull request's state is not open or closed",
    "merged": "the pull request's merged is not true or false",
    "draft": "the pull request's draft is not true or false",
    "head": "the pull request's head is not an object",
    "sha": "the pull request's head.sha is not 40 characters from 0-9a-f",
}
CHECKS_MESSAGES = {
    "unreadable": "cannot read the checks file",
    "not json": "the checks file is not UTF-8 JSON",
    "too large": "the checks file is too deeply nested or too large to read",
    "not an object": "the checks file does not hold a JSON object",
    "check_runs": "the checks file's check_runs is not an array",
    "total_count": "the checks file's total_count is not the number of check runs",
    "run": "the checks file holds a check run that is not an object",
    "id": "the checks file holds a check run whose id is not an integer of 1 or more",
    "name": "the checks file holds a check run whose name is not a string",
    "status": "the checks file holds a check run whose status is not a string",
    "head_sha": "the checks file holds a check run whose head_sha is not a string",
    "conclusion": "the checks file holds a check run whose conclusion is not a string or null",
}


class BadInput(Exception):
    """Carries a fixed one-line reason, never text read from a file."""


def _reject_constant(_name):
    # NaN, Infinity and -Infinity are accepted by the json module but are not JSON.
    raise ValueError("not a JSON value")


def _object_with_unique_keys(pairs):
    # A repeated key would make "the state" of a pull request or "the id" of
    # a check run ambiguous, so such content is refused rather than silently
    # resolved.
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("repeated key")
        result[key] = value
    return result


def load_object(path, messages):
    """Return the JSON object held in the file at path, or raise BadInput."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except (OSError, ValueError, MemoryError):
        raise BadInput(messages["unreadable"]) from None
    try:
        # Strict UTF-8, no byte order mark, standard JSON only.
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_object_with_unique_keys,
        )
    except ValueError:
        raise BadInput(messages["not json"]) from None
    except (RecursionError, MemoryError):
        # Not a verdict on the content: this program could not hold it.
        raise BadInput(messages["too large"]) from None
    if type(value) is not dict:
        raise BadInput(messages["not an object"])
    return value


def is_commit(value):
    """True for a string of exactly 40 characters from 0-9a-f."""
    return (
        type(value) is str
        and len(value) == SHA_LENGTH
        and all(character in SHA_CHARACTERS for character in value)
    )


def validate_pull(pull):
    """Raise BadInput unless the pull request object is valid (S3)."""
    state = pull.get("state")
    if type(state) is not str or state not in ("open", "closed"):
        raise BadInput(PULL_MESSAGES["state"])
    # type() rather than isinstance(): 0 and 1 are not true and false here.
    if type(pull.get("merged")) is not bool:
        raise BadInput(PULL_MESSAGES["merged"])
    if type(pull.get("draft")) is not bool:
        raise BadInput(PULL_MESSAGES["draft"])
    head = pull.get("head")
    if type(head) is not dict:
        raise BadInput(PULL_MESSAGES["head"])
    if not is_commit(head.get("sha")):
        raise BadInput(PULL_MESSAGES["sha"])


def validate_checks(checks):
    """Raise BadInput unless the check runs object is valid (S3)."""
    runs = checks.get("check_runs")
    if type(runs) is not list:
        raise BadInput(CHECKS_MESSAGES["check_runs"])
    total = checks.get("total_count")
    # type() rather than isinstance(): true and false are not integers here.
    if type(total) is not int or total != len(runs):
        raise BadInput(CHECKS_MESSAGES["total_count"])
    for run in runs:
        if type(run) is not dict:
            raise BadInput(CHECKS_MESSAGES["run"])
        identifier = run.get("id")
        if type(identifier) is not int or identifier < 1:
            raise BadInput(CHECKS_MESSAGES["id"])
        for key in ("name", "status", "head_sha"):
            if type(run.get(key)) is not str:
                raise BadInput(CHECKS_MESSAGES[key])
        # The key must be there: an absent conclusion is not a null one.
        if "conclusion" not in run:
            raise BadInput(CHECKS_MESSAGES["conclusion"])
        conclusion = run["conclusion"]
        if conclusion is not None and type(conclusion) is not str:
            raise BadInput(CHECKS_MESSAGES["conclusion"])


def outcome(run):
    """PASSED, FAILED or NOT_COMPLETED for one valid check run."""
    if run["status"] != "completed":
        return NOT_COMPLETED
    return PASSED if run["conclusion"] == "success" else FAILED


def counted_outcome(runs, name, commit):
    """The outcome of the run that counts for one required check, or None.

    Only runs on the given commit under exactly this name are looked at, and
    the one with the highest id counts. GitHub never gives two runs the same
    id; should a file do so, the least favourable of them counts (failed,
    then not completed, then passed), so the answer never depends on the
    order of the list and is never better than any of them.
    """
    highest = None
    outcomes = set()
    for run in runs:
        if run["head_sha"] != commit or run["name"] != name:
            continue
        if highest is None or run["id"] > highest:
            highest = run["id"]
            outcomes = set()
        if run["id"] == highest:
            outcomes.add(outcome(run))
    for candidate in (FAILED, NOT_COMPLETED, PASSED):
        if candidate in outcomes:
            return candidate
    return None


def status(pull, checks):
    """Apply rules (a) to (d) of S5 to a valid pull request and valid checks."""
    if pull["merged"]:
        return "MERGED"
    if pull["state"] == "closed":
        return "CLOSED"
    if pull["draft"]:
        return "DRAFT"
    commit = pull["head"]["sha"]
    outcomes = [counted_outcome(checks["check_runs"], name, commit) for name in REQUIRED_CHECKS]
    failing = [name for name, result in zip(REQUIRED_CHECKS, outcomes) if result == FAILED]
    if failing:
        return "BLOCKED " + " ".join(failing)
    if all(result == PASSED for result in outcomes):
        return "READY"
    return "WAITING"


def _write(descriptor, text):
    # Exact bytes, written at once: no newline translation and nothing left
    # in a buffer to fail after the exit status has been decided.
    data = text.encode("ascii")
    while data:
        written = os.write(descriptor, data)
        if written <= 0:
            raise OSError("nothing was written")
        data = data[written:]


def _report(reason):
    try:
        _write(STDERR, "request_status: %s\n" % reason)
    except OSError:
        pass


def main(argv):
    # A check run's id is "an integer of 1 or more" with no upper bound, so
    # the interpreter's default cap on the length of an integer's text is
    # lifted.
    sys.set_int_max_str_digits(0)
    try:
        if len(argv) != 3:
            raise BadInput(WRONG_ARGUMENTS)
        pull = load_object(argv[1], PULL_MESSAGES)
        checks = load_object(argv[2], CHECKS_MESSAGES)
        # Both are validated in full before anything is reported, so a merged
        # or closed pull request beside invalid checks is still bad input.
        validate_pull(pull)
        validate_checks(checks)
        answer = status(pull, checks)
    except BadInput as problem:
        _report(str(problem))
        return EXIT_BAD_INPUT
    try:
        _write(STDOUT, answer + "\n")
    except OSError:
        _report(CANNOT_WRITE)
        return EXIT_OUTPUT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
