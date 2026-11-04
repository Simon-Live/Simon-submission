"""Print each sign-in code Simon writes to its local outbox, so a judge can sign in without a mail service.

Locally Simon has no mail provider, so part7/mail.py writes each sign-in mail to <state>/outbox/*.eml. run.sh runs
this beside the server: every new mail becomes one line in the terminal with the address, the code and the link.
Reads only that folder; stops when the server process it was given ends.
"""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
import os
from pathlib import Path
import re
import sys
import time


def lines(path: Path) -> str | None:
    """'Sign-in code for <to>: <code>  (or open <link>)' from one outbox mail, or None if it cannot be read."""
    try:
        msg = BytesParser(policy=policy.default).parse(path.open("rb"))
        body = msg.get_body(preferencelist=("plain",)).get_content()
    except (OSError, AttributeError, ValueError):
        return None
    code = re.search(r"Your code: (\S+)", body)
    link = re.search(r"^(https?://\S+)$", body, re.M)
    if not code:
        return None
    return f"Sign-in code for {msg['To']}: {code.group(1)}" + (f"  (or open {link.group(1)})" if link else "")


def main(outbox: str, server_pid: str) -> int:
    folder, seen = Path(outbox), set()
    if folder.is_dir():
        seen = {p.name for p in folder.glob("*.eml")}   # mails from an earlier run are not printed again
    while True:
        try:
            os.kill(int(server_pid), 0)
        except (OSError, ValueError):
            return 0
        if folder.is_dir():
            for path in sorted(folder.glob("*.eml")):
                if path.name not in seen:
                    seen.add(path.name)
                    text = lines(path)
                    if text:
                        print(f"\n>>> {text}\n", flush=True)
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
