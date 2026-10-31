"""Regenerate docs/design/specs/ and docs/design/adr/ from docs/specs/ and docs/adr/.

    python3 scripts/make_design_copies.py [--check] [--root DIR]        (`make design-copies`)

The design copies are the working specs and architecture decision records with the maintainers' host paths, key
locations and workspace tooling neutralised, and a banner line after the title. They used to be kept by hand and
drifted; they are now generated, so a source change shows up as a diff and nothing else changes them.
`docs/design/README.md` (the index) stays hand-written. Every `*.md` of the two source directories is copied
except `TEMPLATE.md`.

Neutralising is a list of named rules (`RULES`), applied in order to the whole text, each matching across line
wraps. A rule that matches nothing does nothing; what a rule misses, the leak guard catches: the run fails (exit
1, nothing written) when any output still contains `/home/`, `~/.config`, `operator-keys`, a key-shaped token or a
staging URL. Add a rule for the sentence the guard names, never an exception to the guard.

`--check` writes nothing and exits 1 when a copy differs from its regenerated text, is missing, has no source, or
trips the guard. Deterministic and idempotent: the output depends only on the sources.
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = {"TEMPLATE.md"}
INDEX = "`docs/design/README.md`"
KINDS = {   # source directory name -> banner of the copies in docs/design/<name>/
    "specs": ("> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text "
              "and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: " + INDEX + "."),
    "adr": ("> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; "
            "where this text and the code disagree, the code and `CONTRACT.md` win. Index: " + INDEX + "."),
}
BANNER_START = "> Design copy of "

KEY_FILE = r"`~/\.config/firm/operator-keys/BASETEN_API_KEY`"
KEY_FILE_WORDS = "the Baseten key file"

# (name, pattern, replacement). Order matters: a specific sentence goes before the general rule for its token.
RULES = (
    ("origin-line", re.compile(r"^Origin: written upstream in .*\n", re.M), ""),
    ("follow-up-ticket", re.compile(r"Follow-up: TICKET-\d+\."), "This is follow-up work."),
    # the Baseten key file
    ("key-file-clause", re.compile(r"(\bkey\s+file)\s+" + KEY_FILE), r"\1"),
    ("key-file-default", re.compile(r"\(default\s+" + KEY_FILE + r"\)"), "(default: " + KEY_FILE_WORDS + ")"),
    ("key-file-article", re.compile(r"\bthe\s+file\s+" + KEY_FILE), KEY_FILE_WORDS),
    ("key-file", re.compile(KEY_FILE), KEY_FILE_WORDS),
    # the staging stack and the hub
    ("hub-staging-contract", re.compile(r"`firm/staging/CONTRACT\.md`"), "the maintainers' staging contract"),
    ("hub-usecase-check", re.compile(r"`firm/check-usecases\.sh[^`]*`\s+from\s+the\s+hub"),
     "the maintainers' use-case check"),
    ("hub-staging-script", re.compile(r"firm/staging/staging\.sh"), "staging.sh"),
    ("staging-state-dir", re.compile(r"(state\s+root)\s+`~/\.local/state/[^`]*`"),
     r"\1 in the maintainers' state directory"),
    ("staging-gateway-url", re.compile(r"`http://127\.0\.0\.1:7100/[^`]*`"), "the staging gateway address"),
    ("staging-login-vars", re.compile(r"`httpCredentials`\s+from\s+`STAGING_USER`\s+and\s+`STAGING_PASSWORD`"),
     "HTTP basic auth from the gateway login (passed in the environment, never printed)"),
    ("staging-login-file", re.compile(r"`~/\.config/firm/staging/credentials`"), "the gateway login file"),
    ("staging-tunnel", re.compile(r"password(\s+or\s+the\s+)tunnel\s+URL"), r"login\1gateway's public address"),
    # host paths
    ("workspace-checkout", re.compile(r"`/home/[^`]*?simon-part-(\d+)`"), r"the Simon Part \1 workspace"),
    ("home-path", re.compile(r"`/home/[^`]*`"), "a path in the maintainers' workspace"),
    ("config-path", re.compile(r"`~/\.config/[^`]*`"), "a file in the maintainers' configuration directory"),
)

LEAKS = (   # (what it is, pattern): none may appear in any output
    ("a host path", re.compile(r"/home/")),
    ("a configuration path", re.compile(r"~/\.config|\$HOME/\.config")),
    ("an operator key location", re.compile(r"operator-keys")),
    ("a key-shaped token", re.compile(
        r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"
        r"|\bAKIA[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{30,}|\bxox[abprs]-[A-Za-z0-9-]{10,}"
        r"|\bBearer\s+[A-Za-z0-9._~+/=-]{20,}"
        r"|(?i:(?:api[_-]?key|secret|token|password)\b)\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{16,}"
        r"|\b(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{32,}\b")),
    ("a staging URL", re.compile(
        r"(?i)https?://\S*(?:trycloudflare|ngrok|loca\.lt|cloudflared|tunnel|staging)\S*"
        r"|https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0|\[::1\]):(?:7100|7123)\b"
        r"|https?://[^/\s:@]+:[^/\s@]+@")),
)


def neutralise(text, names):
    """`text` with every rule applied and the links to other specs and ADRs pointed at their design copies.
    `names` maps a directory name (`specs`, `adr`) to the file names that have a copy."""
    for _, pattern, replacement in RULES:
        text = pattern.sub(replacement, text)

    def link(m):
        return f"docs/design/{m.group(1)}/{m.group(2)}" if m.group(2) in names[m.group(1)] else m.group(0)
    return re.sub(r"(?<![\w/.-])docs/(specs|adr)/([A-Za-z0-9._-]+\.md)", link, text)


def with_banner(text, banner):
    """The banner line right after the title (a banner already there is replaced)."""
    title, _, rest = text.partition("\n")
    if rest.startswith(BANNER_START):
        rest = rest.partition("\n")[2]
    return f"{title}\n{banner}\n{rest}"


def sources(root):
    """{kind: sorted source file names} for the two source directories."""
    out = {}
    for kind in KINDS:
        directory = Path(root) / "docs" / kind
        if not directory.is_dir():
            raise FileNotFoundError(f"{directory} is missing: the working specs and ADRs are the maintainers' "
                                    "workspace files and are not in the published repository")
        out[kind] = sorted(p.name for p in directory.glob("*.md") if p.name not in EXCLUDED)
    return out


def build(root=ROOT):
    """{path relative to root: text of the design copy} for every source file."""
    names = sources(root)
    out = {}
    for kind, files in names.items():
        for name in files:
            text = (Path(root) / "docs" / kind / name).read_text()
            out[f"docs/design/{kind}/{name}"] = with_banner(neutralise(text, names), KINDS[kind])
    return out


def leaks(texts):
    """One sentence per leak: `<file>:<line>: <what> (<snippet>)`."""
    out = []
    for rel, text in texts.items():
        for number, line in enumerate(text.splitlines(), 1):
            for what, pattern in LEAKS:
                for m in pattern.finditer(line):
                    out.append(f"{rel}:{number}: {what} ({m.group(0)[:60]!r}); add a rule to RULES in "
                               "scripts/make_design_copies.py")
    return out


def stale(root, texts):
    """Copies in the two design directories that no source produces."""
    found = []
    for kind in KINDS:
        directory = Path(root) / "docs" / "design" / kind
        for path in sorted(directory.glob("*.md")) if directory.is_dir() else []:
            rel = path.relative_to(root).as_posix()
            if rel not in texts:
                found.append(rel)
    return found


def differences(root, texts):
    """One sentence per copy that is missing or differs from its regenerated text (first lines of the diff)."""
    out = []
    for rel, text in texts.items():
        path = Path(root) / rel
        if not path.is_file():
            out.append(f"{rel}: missing")
        elif path.read_text() != text:
            diff = list(difflib.unified_diff(path.read_text().splitlines(), text.splitlines(), "on disk",
                                             "regenerated", lineterm="", n=0))
            out.append(f"{rel}: differs from its source ({len(diff) - 2} changed lines; first: "
                       f"{next((d for d in diff[2:] if not d.startswith('@@')), '')[:100]!r})")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="make_design_copies.py", description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 when a copy differs or a leak is found")
    ap.add_argument("--root", default=str(ROOT), help="repository root (default: this repository)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        texts = build(root)
    except FileNotFoundError as e:
        print(f"make_design_copies: {e}", file=sys.stderr)
        return 2
    problems = leaks(texts)
    if problems:
        print("make_design_copies: a design copy would leak a host path, a key location or a staging URL; "
              "nothing written:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    extra = stale(root, texts)
    if args.check:
        bad = differences(root, texts) + [f"{rel}: has no source in docs/specs or docs/adr" for rel in extra]
        if bad:
            print("make_design_copies: the design copies are out of date; run python3 scripts/make_design_copies.py\n  "
                  + "\n  ".join(bad), file=sys.stderr)
            return 1
        print(f"make_design_copies: {len(texts)} design copies are current")
        return 0
    written = 0
    for rel, text in texts.items():
        path = root / rel
        if not path.is_file() or path.read_text() != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            written += 1
    for rel in extra:
        (root / rel).unlink()
    print(f"make_design_copies: wrote {written}, unchanged {len(texts) - written}, removed {len(extra)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
