"""`python -m part2.backends <name> [--smoke]` (see part2/backends/__init__.py)."""
import sys

from part2.backends import main

sys.exit(main())
