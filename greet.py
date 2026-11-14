import sys


def greeting(arguments):
    """Return the greeting bytes for the command-line arguments."""
    name = " ".join(arguments).strip()
    if not name:
        return b"Hello.\n"
    try:
        encoded = name.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        encoded = name.encode("utf-8", "surrogatepass")
    return b"Hello, " + encoded + b".\n"


def main():
    if sys.stdout is None:
        return
    sys.stdout.buffer.write(greeting(sys.argv[1:]))


if __name__ == "__main__":
    main()
