"""Turn the line merge_check.py prints into a plain-English card (build request #56).

Usage: python merge_card.py TITLE < RESULT_LINE

TITLE is the pull request's title as one argument. RESULT_LINE is exactly what
merge_check.py printed on standard output: MERGE, or "OWNER: " followed by one
or more reason codes separated by ", ". One trailing line feed is allowed.
The program reads only standard input, writes the card to standard output,
does no network access, merges nothing and posts nothing.

Exit status: 0 success, 1 the card could not be written, 2 bad input.
Runs on Python 3.8 or later; standard library only.
"""

import os
import sys

PREFIX = "merge_card: "
BAD_INPUT = "bad input; usage: python merge_card.py TITLE < RESULT_LINE"
LINE_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85  "

READY = (
    "Ready: every check passed, and the coordinator may merge it under the "
    "owner's standing conditions."
)

SENTENCES = {
    "not-open": "It is closed or still a draft.",
    "not-mergeable": (
        "GitHub says it cannot be merged as it stands (for example it is "
        "behind the main line or has a conflict)."
    ),
    "checks": "The required automatic checks have not all passed.",
    "claude-review": "The Claude review has not passed this exact version.",
    "codex-review": "Codex has not reviewed this exact version, or it found problems.",
    "codex-p1": "Codex marked a serious problem on this version.",
    "paths": (
        "It changes files outside what the request allowed, or the list of "
        "changed files is incomplete."
    ),
    "protected": (
        "It changes a protected area (the spec, the GitHub settings or the "
        "database design), which always needs the owner."
    ),
    "open-question": "It leaves a question open for the owner.",
}


class BadInput(Exception):
    """The input is wrong; the message is one fixed string."""


def read_title(argv):
    """The title is exactly one argument: not empty, one line, valid UTF-8."""
    if len(argv) != 2 or argv[1] == "":
        raise BadInput(BAD_INPUT)
    title = argv[1]
    if any(character in LINE_BREAKS for character in title):
        raise BadInput(BAD_INPUT)
    try:
        title.encode("utf-8")
    except UnicodeEncodeError:
        raise BadInput(BAD_INPUT)
    return title


def read_result():
    """Return None for MERGE, or the list of reason codes for OWNER."""
    try:
        raw = sys.stdin.buffer.read()
        text = raw.decode("utf-8")
    except (AttributeError, OSError, ValueError):
        raise BadInput(BAD_INPUT)
    if text.endswith("\n"):
        text = text[:-1]  # one trailing line break is allowed
    if text == "MERGE":
        return None
    if not text.startswith("OWNER: "):
        raise BadInput(BAD_INPUT)
    codes = text[len("OWNER: "):].split(", ")
    for code in codes:
        if code not in SENTENCES:  # unknown or empty
            raise BadInput(BAD_INPUT)
    if len(set(codes)) != len(codes):
        raise BadInput(BAD_INPUT)
    return codes


def make_card(title, codes):
    lines = ["Pull request: " + title]
    if codes is None:
        lines.append(READY)
        lines.append("Next step: merge it.")
    else:
        lines.append("Needs the owner:")
        for code in codes:
            lines.append("- " + SENTENCES[code])
        lines.append("Next step: the owner decides.")
    return "\n".join(lines) + "\n"


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
    """Write the card to standard output; return True on success."""
    try:
        write_fd(1, text, "strict")
        return True
    except Exception:
        return False


def main(argv):
    try:
        title = read_title(argv)
        card = make_card(title, read_result())
    except BadInput as error:
        return fail(2, str(error))
    if not write_result(card):
        return fail(1, "cannot write the result")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
