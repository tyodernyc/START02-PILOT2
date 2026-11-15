"""Decide whether the coordinator may merge without the owner (build request #46).

Usage: python merge_check.py SNAPSHOT_FILE

SNAPSHOT_FILE is one UTF-8 JSON object that the caller built with `gh api`:
the pull request, its changed files, the check runs of its head commit, its
issue comments and review comments, and the path patterns the request may
change. The program applies the owner's five conditions of 2026-11-15 as
fixed rules and prints either MERGE or OWNER followed by the reasons the
owner is needed. It does no network access, merges nothing, posts nothing
and opens only SNAPSHOT_FILE, for reading.

Input holding NaN, Infinity or -Infinity (not JSON) is bad input.
Exit status: 0 success, 1 the result could not be written, 2 bad input.
Runs on Python 3.8 or later; standard library only.
"""

import fnmatch
import json
import os
import re
import sys

PREFIX = "merge_check: "
DEFAULT_CHECKS = ["tests", "review"]
DEFAULT_PROTECTED = [".github/", "docs/", "apps/backend/prisma/", "AGENTS.md", "CLAUDE.md"]
CLAUDE = "claude[bot]"
CODEX = "chatgpt-codex-connector[bot]"
SHA_RE = re.compile(r"[0-9a-f]{40}")
REVIEWED_RE = re.compile(r"Reviewed commit:[* ]*`([0-9a-f]{7,40})`")
CODEX_CLEAN = ("Didn't find any major issues", "Didn’t find any major issues")
CODEX_BADGES = ("P0 Badge", "P1 Badge")


class BadInput(Exception):
    """The input is wrong; the message is a fixed string."""


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def need(condition, message):
    if not condition:
        raise BadInput(message)


def need_dict(value, message):
    need(isinstance(value, dict), message)
    return value


def need_list(value, message):
    need(isinstance(value, list), message)
    return value


def need_strings(value, message):
    need_list(value, message)
    for item in value:
        need(isinstance(item, str), message)
    return value


def reject_constant(name):
    """NaN, Infinity and -Infinity are not JSON; Python's decoder takes them."""
    raise BadInput("the snapshot file holds " + name + ", which is not JSON")


def load(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        raise BadInput("cannot read the snapshot file")
    try:
        text = raw.decode("utf-8")
        data = json.loads(text, parse_constant=reject_constant)
    except (ValueError, RecursionError, MemoryError):
        raise BadInput("the snapshot file is not UTF-8 JSON")
    return data


def read_pull(value):
    pull = need_dict(value, "pull must be an object")
    need(is_int(pull.get("number")), "the pull request number must be an integer")
    need(isinstance(pull.get("state"), str), "the pull request state must be a string")
    need(isinstance(pull.get("draft"), bool), "the pull request draft flag must be a boolean")
    head = need_dict(pull.get("head"), "the pull request head must be an object")
    sha = head.get("sha")
    need(
        isinstance(sha, str) and SHA_RE.fullmatch(sha) is not None,
        "the pull request head sha must be 40 lower-case hexadecimal characters",
    )
    need("body" in pull, "the pull request needs a body")
    need(
        pull["body"] is None or isinstance(pull["body"], str),
        "the pull request body must be a string or null",
    )
    return pull["state"], pull["draft"], sha, pull["body"]


def read_files(value):
    names = []
    for item in need_list(value, "files must be a list"):
        need_dict(item, "a changed file must be an object")
        need(isinstance(item.get("filename"), str), "a file name must be a string")
        names.append(item["filename"])
    return names


def read_check_runs(value):
    entry = need_dict(value, "check_runs must be an object")
    runs = []
    for run in need_list(entry.get("check_runs"), "check_runs must hold a list"):
        need_dict(run, "a check run must be an object")
        need(is_int(run.get("id")), "a check run id must be an integer")
        need(isinstance(run.get("name"), str), "a check run name must be a string")
        need(isinstance(run.get("status"), str), "a check run status must be a string")
        need("conclusion" in run, "a check run needs a conclusion")
        conclusion = run["conclusion"]
        need(
            conclusion is None or isinstance(conclusion, str),
            "a check run conclusion must be a string or null",
        )
        runs.append((run["id"], run["name"], run["status"], conclusion))
    return runs


def read_comments(value, kind, extra=None):
    """Read a comment list; return (id, login, body, extra field) tuples."""
    found = []
    for comment in need_list(value, kind + " must be a list"):
        need_dict(comment, "a comment must be an object")
        need(is_int(comment.get("id")), "a comment id must be an integer")
        user = need_dict(comment.get("user"), "a comment user must be an object")
        need(isinstance(user.get("login"), str), "a comment login must be a string")
        need(isinstance(comment.get("body"), str), "a comment body must be a string")
        if extra is not None:
            need(isinstance(comment.get(extra), str), "a review comment commit_id must be a string")
        found.append((comment["id"], user["login"], comment["body"], comment.get(extra)))
    return found


def read_allowed(data):
    need("allowed" in data, "the snapshot lacks allowed")
    allowed = need_strings(data["allowed"], "allowed must be a list of strings")
    need(len(allowed) > 0, "allowed must not be empty")
    return allowed


def read_protected(data):
    if "protected" not in data:
        return list(DEFAULT_PROTECTED)
    return need_strings(data["protected"], "protected must be a list of strings")


def read_required(data):
    if "required_checks" not in data:
        return list(DEFAULT_CHECKS)
    names = need_list(data["required_checks"], "required_checks must be a list")
    need(len(names) > 0, "required_checks must not be empty")
    for name in names:
        need(isinstance(name, str) and name != "", "a required check must be a non-empty string")
    need(len(set(names)) == len(names), "required checks must be distinct")
    return names


def read_snapshot(data):
    need_dict(data, "the snapshot must be a JSON object")
    for key in ("pull", "files", "check_runs", "issue_comments", "review_comments"):
        need(key in data, "the snapshot lacks a required key")
    state, draft, sha, body = read_pull(data["pull"])
    return {
        "state": state,
        "draft": draft,
        "sha": sha,
        "body": body,
        "files": read_files(data["files"]),
        "runs": read_check_runs(data["check_runs"]),
        "issue_comments": read_comments(data["issue_comments"], "issue_comments"),
        "review_comments": read_comments(data["review_comments"], "review_comments", "commit_id"),
        "allowed": read_allowed(data),
        "protected": read_protected(data),
        "required": read_required(data),
    }


def split_lines(text):
    """Lines split on line feeds, with one trailing carriage return removed."""
    return [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]


def counted_run(runs, name):
    """The run with exactly this name and the highest id, or None."""
    best = None
    for run in runs:
        if run[1] == name and (best is None or run[0] > best[0]):
            best = run
    return best


def rule_not_open(snap):
    return snap["state"] != "open" or snap["draft"]


def rule_checks(snap):
    for name in snap["required"]:
        run = counted_run(snap["runs"], name)
        if run is None or run[2] != "completed" or run[3] != "success":
            return True
    return False


def latest(comments):
    """The comment with the highest id, or None."""
    best = None
    for comment in comments:
        if best is None or comment[0] > best[0]:
            best = comment
    return best


def rule_claude_review(snap):
    wanted = "HEAD: " + snap["sha"]
    mine = []
    for comment in snap["issue_comments"]:
        if comment[1] != CLAUDE:
            continue
        lines = split_lines(comment[2])
        if len(lines) >= 2 and lines[1] == wanted:
            mine.append((comment[0], lines))
    decisive = latest(mine)
    return decisive is None or "VERDICT: PASS" not in decisive[1]


def rule_codex_review(snap):
    sha = snap["sha"]
    mine = []
    for comment in snap["issue_comments"]:
        if comment[1] != CODEX:
            continue
        if any(sha.startswith(found) for found in REVIEWED_RE.findall(comment[2])):
            mine.append(comment)
    decisive = latest(mine)
    return decisive is None or not any(phrase in decisive[2] for phrase in CODEX_CLEAN)


def rule_codex_p1(snap):
    for comment in snap["review_comments"]:
        if comment[1] == CODEX and comment[3] == snap["sha"]:
            if any(badge in comment[2] for badge in CODEX_BADGES):
                return True
    return False


def rule_paths(snap):
    for name in snap["files"]:
        if not any(fnmatch.fnmatchcase(name, pattern) for pattern in snap["allowed"]):
            return True
    return False


def is_protected(name, prefix):
    if prefix.endswith("/"):
        return name.startswith(prefix)
    return name == prefix


def rule_protected(snap):
    return any(is_protected(name, prefix) for name in snap["files"] for prefix in snap["protected"])


def rule_open_question(snap):
    if snap["body"] is None:
        return False
    lines = split_lines(snap["body"])
    for index, line in enumerate(lines):
        if not line.lstrip("# ").lower().startswith("open question"):
            continue
        following = []
        for later in lines[index + 1:]:
            if later.startswith("#"):
                break
            following.append(later)
        text = "\n".join(following).strip()
        if text.startswith("- "):
            text = text[2:]
        text = text.strip()
        if text != "" and text.lower() != "none":
            return True
    return False


RULES = (
    ("not-open", rule_not_open),
    ("checks", rule_checks),
    ("claude-review", rule_claude_review),
    ("codex-review", rule_codex_review),
    ("codex-p1", rule_codex_p1),
    ("paths", rule_paths),
    ("protected", rule_protected),
    ("open-question", rule_open_question),
)


def decide(snap):
    failed = [code for code, rule in RULES if rule(snap)]
    if not failed:
        return "MERGE"
    return "OWNER: " + ", ".join(failed)


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
    # A valid JSON integer may have any number of digits, so the interpreter's
    # cap on the length of an integer's text is lifted where it exists.
    if hasattr(sys, "set_int_max_str_digits"):
        sys.set_int_max_str_digits(0)
    if len(argv) != 2:
        return fail(2, "usage: python merge_check.py SNAPSHOT_FILE")
    try:
        line = decide(read_snapshot(load(argv[1])))
    except BadInput as error:
        return fail(2, str(error))
    except re.error:
        return fail(2, "a path pattern is not valid")
    except (RecursionError, MemoryError):
        return fail(2, "the snapshot is too large or too deep")
    if not write_result(line):
        return fail(1, "cannot write the result")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
