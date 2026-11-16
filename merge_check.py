"""Decide whether the coordinator may merge without the owner (build requests #46, #48, #50, #52, #58 and #63).

Usage: python merge_check.py SNAPSHOT_FILE

SNAPSHOT_FILE is one UTF-8 JSON object that the caller built with `gh api`:
the pull request, its changed files, the check runs of its head commit, its
issue comments and review comments, and the path patterns the request may
change. The program applies the owner's five conditions of 2026-11-15 as
fixed rules and prints either MERGE or OWNER followed by the reasons the
owner is needed. It does no network access, merges nothing, posts nothing
and opens only SNAPSHOT_FILE, for reading.

Input holding NaN, Infinity or -Infinity (not JSON) is bad input, and so is a
JSON object that holds the same key twice (at any depth) or a snapshot file that
starts with a byte order mark (snapshot.py never writes one).
Exit status: 0 success, 1 the result could not be written, 2 bad input.
Runs on Python 3.8 or later; standard library only.
"""

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
CODEX_BADGES = ("P0 Badge", "P1 Badge", "[P0", "[P1")
CODEX_LINE_RE = re.compile(r"^[ \t]*P[01][: ]", re.MULTILINE)
MIN_REVIEWED = 10  # a Codex "Reviewed commit" value needs at least this many hex characters
QUESTION_STARTS = ("question for the founder", "question for the owner", "founder question")


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


def reject_repeated_key(pairs):
    """A JSON object with the same key twice is bad input; the last value must not win silently."""
    result = {}
    for key, value in pairs:
        need(key not in result, "the snapshot file holds a repeated key")
        result[key] = value
    return result


def load(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        raise BadInput("cannot read the snapshot file")
    need(not raw.startswith(b"\xef\xbb\xbf"), "the snapshot file starts with a byte order mark")
    try:
        text = raw.decode("utf-8")
        data = json.loads(text, parse_constant=reject_constant, object_pairs_hook=reject_repeated_key)
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
    state = pull.get("mergeable_state")
    need(
        state is None or isinstance(state, str),
        "the pull request mergeable_state must be a string or null",
    )
    return pull["state"], pull["draft"], sha, pull["body"], state


def read_files(value):
    """Return every changed path (a rename counts both names) and the entry count."""
    names = []
    entries = need_list(value, "files must be a list")
    for item in entries:
        need_dict(item, "a changed file must be an object")
        need(isinstance(item.get("filename"), str), "a file name must be a string")
        names.append(item["filename"])
        if "previous_filename" in item:
            need(isinstance(item["previous_filename"], str), "a previous file name must be a string")
            names.append(item["previous_filename"])
    return names, len(entries)


def read_changed_files(pull):
    """The pull request's own count of changed files, or None when it is absent or null."""
    value = pull.get("changed_files")
    need(value is None or is_int(value), "the pull request changed_files must be an integer or null")
    need(value is None or value >= 0, "the pull request changed_files must not be negative")
    return value


def read_check_runs(value):
    """Return the runs and whether the list is incomplete (total_count is larger)."""
    entry = need_dict(value, "check_runs must be an object")
    total = entry.get("total_count")
    need(total is None or is_int(total), "the check run total_count must be an integer or null")
    need(total is None or total >= 0, "the check run total_count must not be negative")
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
    return runs, total is not None and total > len(runs)


def read_comments(value, kind, extra=None):
    """Read a comment list; return (id, login, body, extra field) tuples."""
    found = []
    for comment in need_list(value, kind + " must be a list"):
        need_dict(comment, "a comment must be an object")
        need(is_int(comment.get("id")), "a comment id must be an integer")
        need("user" in comment, "a comment needs a user")
        user = comment["user"]
        if user is not None:
            need_dict(user, "a comment user must be an object or null")
            need(isinstance(user.get("login"), str), "a comment login must be a string")
        need(isinstance(comment.get("body"), str), "a comment body must be a string")
        if extra is not None:
            need(isinstance(comment.get(extra), str), "a review comment commit_id must be a string")
        if user is None:
            continue  # a deleted account: neither a Claude review nor a Codex comment
        found.append((comment["id"], user["login"], comment["body"], comment.get(extra)))
    return found


def read_allowed(data):
    need("allowed" in data, "the snapshot lacks allowed")
    allowed = need_strings(data["allowed"], "allowed must be a list of strings")
    need(len(allowed) > 0, "allowed must not be empty")
    return allowed


def read_protected(data):
    """The default prefixes always apply; a listed `protected` only adds to them."""
    extra = []
    if "protected" in data:
        extra = need_strings(data["protected"], "protected must be a list of strings")
    return list(DEFAULT_PROTECTED) + extra


def read_truncated(data):
    value = data.get("files_truncated")
    need(value is None or isinstance(value, bool), "files_truncated must be a boolean or null")
    return value is True


def read_required(data):
    """`tests` and `review` are always required; a listed `required_checks` only adds names."""
    required = list(DEFAULT_CHECKS)
    if "required_checks" not in data:
        return required
    names = need_list(data["required_checks"], "required_checks must be a list")
    need(len(names) > 0, "required_checks must not be empty")
    for name in names:
        need(isinstance(name, str) and name != "", "a required check must be a non-empty string")
    need(len(set(names)) == len(names), "required checks must be distinct")
    return required + [name for name in names if name not in required]


def read_snapshot(data):
    need_dict(data, "the snapshot must be a JSON object")
    for key in ("pull", "files", "check_runs", "issue_comments", "review_comments"):
        need(key in data, "the snapshot lacks a required key")
    state, draft, sha, body, mergeable = read_pull(data["pull"])
    names, count = read_files(data["files"])
    runs, runs_incomplete = read_check_runs(data["check_runs"])
    return {
        "state": state,
        "mergeable": mergeable,
        "draft": draft,
        "sha": sha,
        "body": body,
        "files": names,
        "file_count": count,
        "changed_files": read_changed_files(data["pull"]),
        "runs": runs,
        "runs_incomplete": runs_incomplete,
        "files_truncated": read_truncated(data),
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


def rule_not_mergeable(snap):
    return snap["mergeable"] != "clean"  # absent, null, unknown or anything but clean


def rule_checks(snap):
    if snap["runs_incomplete"]:
        return True  # the list of check runs is cut short
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
    return decisive is None or len(decisive[1]) < 3 or decisive[1][2] != "VERDICT: PASS"


def codex_summary(snap):
    """The Codex comment that decides codex-review: the latest one for the head, or None."""
    sha = snap["sha"]
    mine = []
    for comment in snap["issue_comments"]:
        if comment[1] != CODEX:
            continue
        if any(len(found) >= MIN_REVIEWED and sha.startswith(found) for found in REVIEWED_RE.findall(comment[2])):
            mine.append(comment)
    return latest(mine)


def rule_codex_review(snap):
    decisive = codex_summary(snap)
    return decisive is None or not any(phrase in decisive[2] for phrase in CODEX_CLEAN)


def serious(text):
    """True if the Codex text holds a P0 or P1 marker."""
    return any(badge in text for badge in CODEX_BADGES) or CODEX_LINE_RE.search(text) is not None


def rule_codex_p1(snap):
    decisive = codex_summary(snap)
    if decisive is not None and serious(decisive[2]):
        return True
    for comment in snap["review_comments"]:
        if comment[1] == CODEX and comment[3] == snap["sha"] and serious(comment[2]):
            return True
    return False


def set_regex(stuff):
    """Translate the inside of a `[...]` set; it never takes in `/`.

    Every character is escaped on its own, so no text inside a set can reach
    the regular expression engine as syntax. A reversed range such as `z-a`
    takes in nothing.
    """
    negated = stuff[:1] == "!"
    if negated:
        stuff = stuff[1:]
    items = []
    k = 0
    while k < len(stuff):
        if k + 2 < len(stuff) and stuff[k + 1] == "-":
            if stuff[k] <= stuff[k + 2]:
                items.append(set_char(stuff[k]) + "-" + set_char(stuff[k + 2]))
            k += 3
        else:
            items.append(set_char(stuff[k]))
            k += 1
    if negated:
        return "(?!/)[^" + "".join(items) + "]" if items else "[^/]"
    return "(?!/)[" + "".join(items) + "]" if items else "(?!)"


def set_char(char):
    return "\\" + char if char in "\\[]^-&~|" else char


def pattern_regex(pattern):
    """Translate an allowed-path pattern to a regular expression.

    `*`, `?` and a `[...]` set never cross a `/`. `**` as a whole folder name
    stands for any number of whole folders (`a/**/b` takes in `a/b` and `a/x/y/b`;
    a final `/**` takes in everything below the folder). Any other run of
    stars acts as one `*`. A pattern without wildcards must equal the name.
    """
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            j = i
            while j < n and pattern[j] == "*":
                j += 1
            whole = j - i == 2 and (i == 0 or pattern[i - 1] == "/") and (j == n or pattern[j] == "/")
            if whole and j == n:
                out.append(".+")
            elif whole:
                out.append("(?:[^/]+/)*")
                j += 1  # the slash after ** belongs to it
            else:
                out.append("[^/]*")
            i = j
        elif char == "?":
            out.append("[^/]")
            i += 1
        elif char == "[":
            j = i + 1
            if j < n and pattern[j] == "!":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(char))
                i += 1
            else:
                out.append(set_regex(pattern[i + 1 : j]))
                i = j + 1
        else:
            out.append(re.escape(char))
            i += 1
    return "".join(out)


def pattern_matches(name, pattern):
    try:
        return re.fullmatch(pattern_regex(pattern), name, re.DOTALL) is not None
    except re.error:
        return False  # a pattern the translation cannot express matches no path


def path_allowed(name, patterns):
    return any(pattern_matches(name, pattern) for pattern in patterns)


def rule_paths(snap):
    if snap["files_truncated"]:
        return True  # the list of changed files is cut short
    if snap["changed_files"] is not None and snap["changed_files"] > snap["file_count"]:
        return True  # the pull request has more changed files than the list holds
    if snap["file_count"] == 0:
        return True  # nothing changed, so there is nothing to merge
    for name in snap["files"]:
        if not path_allowed(name, snap["allowed"]):
            return True
    return False


def is_protected(name, prefix):
    if prefix.endswith("/"):
        return name.startswith(prefix)
    return name == prefix


def rule_protected(snap):
    return any(is_protected(name, prefix) for name in snap["files"] for prefix in snap["protected"])


def is_heading(line):
    """A heading line starts with # followed by a space or another #."""
    return len(line) >= 2 and line[0] == "#" and line[1] in "# "


def fence_marker(line):
    """Return (character, length, rest of the line) if the line is a fence line, else None.

    A fence line is indented 0 to 3 spaces and then starts with three or more
    backticks or three or more tildes; the run is all of the same character.
    After a run of backticks the rest of the line may not hold a backtick.
    """
    indent = len(line) - len(line.lstrip(" "))
    if indent > 3:
        return None
    text = line[indent:]
    if text[:1] not in ("`", "~"):
        return None
    character = text[0]
    length = len(text) - len(text.lstrip(character))
    if length < 3:
        return None
    rest = text[length:]
    if character == "`" and "`" in rest:
        return None  # the text after backticks may not hold a backtick: this is inline code
    return character, length, rest


def fenced_lines(lines):
    """For each line, True if it is a fence line or lies inside a fenced code block.

    A fence opens on a fence line (see fence_marker). It closes only on a fence
    line of the same character with at least as many characters as the opening
    line and nothing after them but spaces. A block that is never closed runs
    to the end.
    """
    flags = []
    opened = None
    for line in lines:
        marker = fence_marker(line)
        if opened is None:
            if marker is None:
                flags.append(False)
            else:
                opened = marker
                flags.append(True)
        else:
            flags.append(True)
            if (
                marker is not None
                and marker[0] == opened[0]
                and marker[1] >= opened[1]
                and marker[2].strip(" ") == ""
            ):
                opened = None
    return flags


def heading_text(line):
    """The text on an open-question heading line after "open question(s)" and any `:` or `-`."""
    rest = line.lstrip("# ")[len("open question") :]
    if rest[:1] in ("s", "S"):
        rest = rest[1:]
    return rest.lstrip(" \t:-").rstrip(" \t#").strip()


def is_none(text):
    return text.lower() in ("none", "none.")


def rule_open_question(snap):
    if snap["body"] is None:
        return False
    lines = split_lines(snap["body"])
    fenced = fenced_lines(lines)
    for index, line in enumerate(lines):
        if fenced[index]:
            continue
        if line.lstrip("#-* \t").lower().startswith(QUESTION_STARTS):
            return True
        if not line.lstrip("# ").lower().startswith("open question"):
            continue
        own = heading_text(line)
        if own != "" and not is_none(own):
            return True
        following = []
        for position in range(index + 1, len(lines)):
            later = lines[position]
            if not fenced[position] and is_heading(later):
                break
            following.append(later)
        text = "\n".join(following).strip()
        if text.startswith("- "):
            text = text[2:]
        text = text.strip()
        if text != "" and not is_none(text):
            return True
    return False


RULES = (
    ("not-open", rule_not_open),
    ("not-mergeable", rule_not_mergeable),
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
