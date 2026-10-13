#!/usr/bin/env python3
"""Write the last PASS's D4.2 `execstart_sha256` to standard output: the one value, no line break.

  python3 bin/last-pass-execstart.py <the last PASS's private box bundle> | pbcopy

The collector takes that value as --last-pass-execstart. The public report shows it abbreviated;
the full value is only in the private box bundle. Piped to the clipboard it is never shown on
screen. Writes nothing, and exits 1, when the file cannot be read or the field is not exactly 64
lowercase hex characters, or when standard output cannot be written: no error text, so no path and no content. Stdlib only."""
import json, os, re, sys


def main(argv):
    try:
        with open(argv[1], encoding="utf-8") as f:
            value = json.load(f)["items"]["D4.2"]["data"]["execstart_sha256"]
    except Exception:
        return 1
    if not (isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)):
        return 1
    try:
        sys.stdout.write(value)
        sys.stdout.flush()
    except BaseException:
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except BaseException:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
