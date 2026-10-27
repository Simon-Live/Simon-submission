"""`python3 -m part3 run --in <pose3d.json> --out <skeleton.json> [--flip auto|on|off]`."""

import sys

from part3.cli import main

if __name__ == "__main__":
    sys.exit(main())
