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
    data = memoryview(greeting(sys.argv[1:]))
    # Write through the unbuffered layer. Nothing is then left in a buffer
    # for the interpreter to flush at exit, so a standard output that cannot
    # be written (reader gone, device full) ends the program quietly.
    stream = sys.stdout.buffer
    stream = getattr(stream, "raw", stream)
    try:
        while data:
            written = stream.write(data)
            if not written:
                return
            data = data[written:]
    except OSError:
        return


if __name__ == "__main__":
    main()
