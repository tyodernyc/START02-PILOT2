#!/usr/bin/env python3
"""Automatic-review gate for one pull-request run.

Usage: review_gate.py COMMENTS_FILE
Environment: HEAD_SHA (the 40-character head commit of this run) and
RUN_START (UTC time this run started, YYYY-MM-DDTHH:MM:SSZ).

COMMENTS_FILE holds what "gh api --paginate" printed for the pull request's
issue comments: one JSON array, an array of pages, or several arrays one
after another.

Exit 0 only when the newest accepted review comment says PASS. A comment is
accepted only if the reviewer wrote it, it starts with the review heading,
it names this run's head commit, and it was created at or after RUN_START.
Everything else exits 1.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

REVIEWER = "claude[bot]"
HEADING = "## Automatic review"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


def parse_time(text):
    """Return an aware UTC datetime, or None if text is not in TIME_FORMAT."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def load_comments(text):
    """Parse gh output into a flat list of comment objects.

    Raises ValueError if the text is not JSON or holds anything that is not a
    comment object or a list of them.
    """
    decoder = json.JSONDecoder()
    documents = []
    position = 0
    length = len(text)
    while True:
        while position < length and text[position].isspace():
            position += 1
        if position >= length:
            break
        document, position = decoder.raw_decode(text, position)
        documents.append(document)
    if not documents:
        raise ValueError("no JSON found")
    comments = []

    def add(item):
        if isinstance(item, list):
            for inner in item:
                add(inner)
        elif isinstance(item, dict):
            comments.append(item)
        else:
            raise ValueError("unexpected JSON value")

    for document in documents:
        if not isinstance(document, list):
            raise ValueError("top-level JSON value is not a list")
        add(document)
    return comments


def body_lines(comment):
    body = comment.get("body")
    if not isinstance(body, str):
        return []
    return body.replace("\r", "").split("\n")


def is_accepted(comment, head_sha, run_start):
    user = comment.get("user")
    if not isinstance(user, dict) or user.get("login") != REVIEWER:
        return False
    lines = body_lines(comment)
    if not lines or not lines[0].startswith(HEADING):
        return False
    head_lines = [line.rstrip() for line in lines if line.startswith("HEAD:")]
    if head_lines != ["HEAD: " + head_sha]:
        return False
    created = parse_time(comment.get("created_at"))
    if created is None or created < run_start:
        return False
    return True


def decide(comments, head_sha, run_start_text):
    """Return (passed, reason)."""
    if not isinstance(head_sha, str) or not SHA_PATTERN.fullmatch(head_sha):
        return False, "HEAD_SHA is not a 40-character commit id"
    run_start = parse_time(run_start_text)
    if run_start is None:
        return False, "RUN_START is not a UTC time"
    accepted = [
        (parse_time(comment.get("created_at")), index, comment)
        for index, comment in enumerate(comments)
        if is_accepted(comment, head_sha, run_start)
    ]
    if not accepted:
        return False, "no review comment for this head commit from this run"
    accepted.sort(key=lambda entry: (entry[0], entry[1]))
    newest = accepted[-1][2]
    verdicts = [line.rstrip() for line in body_lines(newest) if line.startswith("VERDICT:")]
    if len(verdicts) != 1:
        return False, "review comment has %d verdict lines, need exactly one" % len(verdicts)
    if verdicts[0] == "VERDICT: PASS":
        return True, "review verdict PASS for this head commit"
    if verdicts[0] == "VERDICT: FAIL":
        return False, "review verdict FAIL"
    return False, "unparseable verdict"


def main(argv):
    if len(argv) != 2:
        print("GATE: usage: review_gate.py COMMENTS_FILE")
        return 1
    try:
        with open(argv[1], encoding="utf-8") as handle:
            comments = load_comments(handle.read())
    except (OSError, ValueError) as error:
        print("GATE: could not read comments: %s" % error)
        return 1
    passed, reason = decide(
        comments, os.environ.get("HEAD_SHA", ""), os.environ.get("RUN_START", "")
    )
    print("GATE: %d comments read; %s" % (len(comments), reason))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
