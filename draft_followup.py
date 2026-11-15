"""Draft a follow-up build request from an automatic review (build request #42).

Usage: python draft_followup.py PULL_FILE COMMENTS_FILE

PULL_FILE is the UTF-8 JSON object REST "get a pull request" returns;
COMMENTS_FILE is the UTF-8 JSON array REST "list issue comments" returns for
that pull request. The program finds the automatic review of the pull
request's head commit and prints a draft follow-up request that lists the
review's LEFTOVER findings. It never files, posts or changes anything, does
no network access and opens only the two named files, for reading.

Exit status: 0 success, 1 the result could not be written, 2 bad input.
Runs on Python 3.8 or later; standard library only.
"""

import json
import re
import sys

PREFIX = "draft_followup: "
REVIEWER = "claude[bot]"
SHA_RE = re.compile(r"[0-9a-f]{40}")
MAX_ITEM = 1000

TEMPLATE_HEAD = (
    "TITLE: Build request: follow-up to pull request {number}\n"
    "## Request\n"
    "\n"
    "Follow up the LEFTOVER findings of the automatic review of pull request "
    "{number} (head commit {sha}). Check each finding against the code as it "
    "is now. Fix only what you reproduce and what lies within the allowed "
    "paths; for anything else, say why it was not fixed.\n"
    "\n"
    "## Findings\n"
    "\n"
)
TEMPLATE_TAIL = (
    "\n"
    "## Deliverables\n"
    "\n"
    "- Allowed paths: TO BE FILLED IN BY THE COORDINATOR BEFORE FILING.\n"
    "- A test for each fix. All existing tests keep passing.\n"
    "- Do not merge.\n"
    "\n"
    "## Decide and record\n"
    "\n"
    "Where this request is silent, make the simplest choice consistent with "
    "the findings and list it in the pull request body under "
    '"Assumptions". Do not stop to ask.\n'
)


class BadInput(Exception):
    """The input is wrong; the message is a fixed string."""


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def need(condition, message):
    if not condition:
        raise BadInput(message)


def load(path, what):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except (OSError, ValueError):
        raise BadInput("cannot read the " + what + " file")
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError, MemoryError):
        raise BadInput("the " + what + " file is not UTF-8 JSON")


def check_pull(pull):
    need(isinstance(pull, dict), "the pull request file is not a JSON object")
    number = pull.get("number")
    need(is_int(number) and number >= 1, "bad pull request number")
    head = pull.get("head")
    need(isinstance(head, dict), "bad pull request head")
    sha = head.get("sha")
    need(
        isinstance(sha, str) and SHA_RE.fullmatch(sha) is not None,
        "bad head commit",
    )
    return number, sha


def check_comments(comments):
    need(isinstance(comments, list), "the comments file is not a JSON array")
    for comment in comments:
        need(isinstance(comment, dict), "bad comment")
        need(is_int(comment.get("id")), "bad comment id")
        user = comment.get("user")
        need(
            isinstance(user, dict) and isinstance(user.get("login"), str),
            "bad comment user",
        )
        need(isinstance(comment.get("body"), str), "bad comment body")


def split_lines(body):
    lines = body.split("\n")
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def find_review(comments, sha):
    """The matching comment with the highest id, as its list of lines."""
    best_id = None
    best_lines = None
    for comment in comments:
        if comment["user"]["login"] != REVIEWER:
            continue
        lines = split_lines(comment["body"])
        if len(lines) < 2 or lines[1] != "HEAD: " + sha:
            continue
        if best_id is None or comment["id"] > best_id:
            best_id = comment["id"]
            best_lines = lines
    return best_lines


def make_safe(text):
    kept = "".join(c for c in text if ord(c) >= 0x20 and ord(c) != 0x7F)
    kept = kept.replace("@", "(at)").strip()
    if len(kept) > MAX_ITEM:
        kept = kept[:MAX_ITEM] + "..."
    return kept


def leftover_items(lines):
    items = []
    in_section = False
    for line in lines:
        if not in_section:
            if line == "LEFTOVER:":
                in_section = True
            continue
        if line.startswith("- "):
            if line == "- none":
                continue
            text = make_safe(line[2:])
            if text:
                items.append(text)
        elif line.endswith(":"):
            break
    return items


def build_output(number, sha, comments):
    lines = find_review(comments, sha)
    if lines is None:
        return "NO REVIEW\n"
    items = leftover_items(lines)
    if not items:
        return "NO LEFTOVERS\n"
    numbered = "".join(
        "%d. %s\n" % (index, item) for index, item in enumerate(items, 1)
    )
    return TEMPLATE_HEAD.format(number=number, sha=sha) + numbered + TEMPLATE_TAIL


def write_stdout(text):
    # Text that cannot be encoded (a lone surrogate from a JSON escape) is
    # written with a replacement character instead of failing.
    data = text.encode("utf-8", "replace")
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def main(argv):
    try:
        need(len(argv) == 3, "usage: python draft_followup.py PULL_FILE COMMENTS_FILE")
        number, sha = check_pull(load(argv[1], "pull request"))
        comments = load(argv[2], "comments")
        check_comments(comments)
        output = build_output(number, sha, comments)
    except BadInput as error:
        try:
            sys.stderr.write(PREFIX + str(error) + "\n")
            sys.stderr.flush()
        except Exception:
            pass
        return 2
    try:
        write_stdout(output)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
