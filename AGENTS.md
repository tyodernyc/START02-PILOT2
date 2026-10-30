# AGENTS.md

## Code Review Rules

### Runtime correctness
- Report every way the changed code can crash, raise an unhandled error, or give a wrong result, including when it is run with missing, empty or unusual input, even if the current tests pass.
- Check what happens when a command-line program in this repository is run with no arguments.
- Never skip a reproducible failure because it depends on input.

### Review verdict
- Mark each finding BLOCKING (a reproducible crash, a wrong result, a regression or a security defect) or LEFTOVER (worth fixing, does not break use).
- Treat every BLOCKING finding as priority P1 or higher.
- End the review with one line: "VERDICT: PASS" if there is no BLOCKING finding, otherwise "VERDICT: FAIL".
- Never change, approve or merge code.
