import sys


def greeting(arguments):
    """Return the greeting line for the given command-line arguments.

    The name is the arguments joined by single spaces, with leading and
    trailing whitespace then removed. It is used as given: never evaluated
    and never used as a format template.
    """
    name = " ".join(arguments).strip()
    if name:
        return "Hello, " + name + "."
    return "Hello."


def encode(line):
    """Return the line as UTF-8 bytes, without raising for any argument.

    An argument that was not valid text reaches Python as lone surrogate
    code points, which plain UTF-8 encoding refuses. Those are written
    back as the bytes they came from where that is possible.
    """
    try:
        return line.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        return line.encode("utf-8", "surrogatepass")


def main():
    data = encode(greeting(sys.argv[1:]) + "\n")
    # sys.stdout is None when the program is started with standard output
    # closed; there is then nowhere to write, as with print().
    if sys.stdout is not None:
        sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()
