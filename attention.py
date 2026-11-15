"""List everything that is waiting on the owner (build request #38).

Usage: python attention.py SNAPSHOT_FILE

SNAPSHOT_FILE is one UTF-8 JSON object holding a snapshot of a repository:
open issues, open pull requests, check runs and comments, as the caller
fetched them with `gh api`. The program does no network access and opens
only SNAPSHOT_FILE, for reading. It prints a short fixed-format list.

Exit status: 0 success, 1 the result could not be written, 2 bad input.
Runs on Python 3.8 or later; standard library only.
"""

import json
import os
import re
import sys

PREFIX = "attention: "
DEFAULT_CHECKS = ["tests", "review"]
OWNER = "tyodernyc"
REVIEWER = "claude[bot]"
BUILD_TITLE = "Build request:"
SHA_RE = re.compile(r"[0-9a-f]{40}")


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


def load(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        raise BadInput("cannot read the snapshot file")
    try:
        text = raw.decode("utf-8")
        data = json.loads(text)
    except (ValueError, RecursionError, MemoryError):
        raise BadInput("the snapshot file is not UTF-8 JSON")
    return data


def read_issues(value):
    issues = []
    for item in need_list(value, "issues must be a list"):
        need_dict(item, "an issue must be an object")
        if "pull_request" in item:
            continue
        need(is_int(item.get("number")), "an issue number must be an integer")
        need(isinstance(item.get("title"), str), "an issue title must be a string")
        issues.append((item["number"], item["title"]))
    return issues


def read_pulls(value):
    pulls = []
    for item in need_list(value, "pulls must be a list"):
        need_dict(item, "a pull request must be an object")
        need(is_int(item.get("number")), "a pull request number must be an integer")
        need(isinstance(item.get("draft"), bool), "a pull request draft flag must be a boolean")
        head = need_dict(item.get("head"), "a pull request head must be an object")
        need(isinstance(head.get("ref"), str), "a pull request head ref must be a string")
        sha = head.get("sha")
        need(
            isinstance(sha, str) and SHA_RE.fullmatch(sha) is not None,
            "a pull request head sha must be 40 lower-case hexadecimal characters",
        )
        pulls.append((item["number"], item["draft"], head["ref"], sha))
    return pulls


def read_check_runs(value):
    table = {}
    for key, entry in need_dict(value, "check_runs must be an object").items():
        need_dict(entry, "a check run list must be an object")
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
        table[key] = runs
    return table


def read_comments(value):
    table = {}
    for key, entry in need_dict(value, "comments must be an object").items():
        found = []
        for comment in need_list(entry, "a comment list must be a list"):
            need_dict(comment, "a comment must be an object")
            need(is_int(comment.get("id")), "a comment id must be an integer")
            user = need_dict(comment.get("user"), "a comment user must be an object")
            need(isinstance(user.get("login"), str), "a comment login must be a string")
            need(isinstance(comment.get("body"), str), "a comment body must be a string")
            found.append((comment["id"], user["login"], comment["body"]))
        table[key] = found
    return table


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
    for key in ("issues", "pulls", "check_runs", "comments"):
        need(key in data, "the snapshot lacks a required key")
    return (
        read_issues(data["issues"]),
        read_pulls(data["pulls"]),
        read_check_runs(data["check_runs"]),
        read_comments(data["comments"]),
        read_required(data),
    )


def counted_run(runs, name):
    """The run with exactly this name and the highest id, or None."""
    best = None
    for run in runs:
        if run[1] == name and (best is None or run[0] > best[0]):
            best = run
    return best


def judge(runs, required):
    """Return ("FAILED", [names]), ("MERGE", []) or ("WAITING", [])."""
    counted = [(name, counted_run(runs, name)) for name in required]
    failed = [
        name
        for name, run in counted
        if run is not None and run[2] == "completed" and run[3] != "success"
    ]
    if failed:
        return "FAILED", failed
    if all(run is not None and run[2] == "completed" and run[3] == "success" for _, run in counted):
        return "MERGE", []
    return "WAITING", []


def split_lines(body):
    return body.replace("\r\n", "\n").split("\n")


def leftover_count(comments, sha):
    """The leftover count of the review for this head commit, or "unknown"."""
    wanted = "HEAD: " + sha
    review = None
    for comment in comments:
        if comment[1] == REVIEWER and wanted in split_lines(comment[2]):
            if review is None or comment[0] > review[0]:
                review = comment
    if review is None:
        return "unknown"
    lines = split_lines(review[2])
    if "LEFTOVER:" not in lines:
        return "unknown"
    count = 0
    for line in lines[lines.index("LEFTOVER:") + 1:]:
        if line.endswith(":") and not line.startswith("- "):
            break
        if line.startswith("- ") and line != "- none":
            count += 1
    return count


def build(snapshot):
    issues, pulls, check_runs, comments, required = snapshot
    merge, failed, waiting = [], [], []
    for number, draft, _ref, sha in pulls:
        if draft:
            continue
        verdict, names = judge(check_runs.get(sha, []), required)
        if verdict == "MERGE":
            count = leftover_count(comments.get(str(number), []), sha)
            merge.append((number, "MERGE WANTED: pull request %d (leftovers: %s)" % (number, count)))
        elif verdict == "FAILED":
            failed.append((number, "FAILED: pull request %d (%s)" % (number, ", ".join(names))))
        else:
            waiting.append((number, "WAITING: pull request %d" % number))
    refs = set(ref for _n, _d, ref, _s in pulls)
    decision, queued = [], []
    for number, title in issues:
        if not title.startswith(BUILD_TITLE) or ("req-%d" % number) in refs:
            continue
        found = comments.get(str(number), [])
        if not found:
            queued.append((number, "QUEUED: issue %d" % number))
        elif max(found, key=lambda comment: comment[0])[1] != OWNER:
            decision.append((number, "DECISION WANTED: issue %d" % number))
    lines = []
    for group in (merge, decision, failed, waiting, queued):
        lines.extend(text for _number, text in sorted(group, key=lambda pair: pair[0]))
    return lines or ["NOTHING WAITING"]


def fail(code, message):
    try:
        sys.stderr.write(PREFIX + message + "\n")
        sys.stderr.flush()
    except Exception:
        pass
    return code


def write_result(lines):
    """Write the lines to standard output; return True on success."""
    try:
        data = "".join(line + "\n" for line in lines).encode("utf-8")
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return True
    except Exception:
        try:
            null = os.open(os.devnull, os.O_WRONLY)
            os.dup2(null, 1)
        except Exception:
            pass
        return False


def main(argv):
    if len(argv) != 2:
        return fail(2, "usage: python attention.py SNAPSHOT_FILE")
    try:
        lines = build(read_snapshot(load(argv[1])))
    except BadInput as error:
        return fail(2, str(error))
    except (RecursionError, MemoryError):
        return fail(2, "the snapshot is too large or too deep")
    if not write_result(lines):
        return fail(1, "cannot write the result")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
