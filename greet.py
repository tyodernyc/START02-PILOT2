import sys


def greeting(args):
    """Return the greeting line for the given command-line arguments.

    All arguments are joined with single spaces. Empty and whitespace-only
    arguments collapse away, so a missing name, an empty name and a
    whitespace-only name are all treated the same and default to "World".
    """
    name = " ".join(" ".join(args).split())
    if not name:
        name = "World"
    return "Hello, {}.".format(name)


def main(args):
    line = greeting(args)
    # Written as bytes so the text layer's encoding cannot raise
    # UnicodeEncodeError: an argument carrying undecodable bytes (surrogates
    # from surrogateescape) or a name stdout cannot encode becomes "?" here
    # instead of a traceback.
    sys.stdout.buffer.write(line.encode("utf-8", "replace") + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
