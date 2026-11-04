"""The legal drafts in `docs/legal/` as HTML pages (docs/specs/legal-pages.md, HARDENING section 8, LEG-C3).

`render(name)` turns one draft into a page. The renderer knows only what the drafts use: `#` to `###` headings,
paragraphs, `- ` lists, pipe tables, `**bold**`, `` `code` `` and `[text](link)` where the link is relative or https.
Every character from the file is escaped before any markup is added, so a draft cannot inject markup or script.
An HTML comment (`<!-- ... -->`, one or more lines) is a drafting note for the operator: it is removed
before rendering and never reaches the page (a11y-copy B9, R13).

The postal address is not in the source. Prod reads it from the file `SIMON7_POSTAL_ADDRESS` in `PROD_SECRETS_DIR`, and every
other environment shows `TEST_ADDRESS`. A page or mail that needs an address and has none is not produced (docs/specs/legal-pages.md AC-LP12).
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from part7 import config, keys
from part7.prod_mode import is_prod

LEGAL_DIR = config.REPO_ROOT / "docs" / "legal"
# The one place each value lives; a page names it by token, so a change is one commit (operator decisions, 3 November 2026).
COMPANY_NAME = "Simon Live LLC"
DMCA_AGENT_NAME = "Mohamed Alborati"  # the copyright page only
TOKENS = {"{{COMPANY_NAME}}": COMPANY_NAME, "{{DMCA_AGENT_NAME}}": DMCA_AGENT_NAME}
ADDRESS_TOKEN = "{{DMCA_AGENT_ADDRESS}}"
ADDRESS_SETTING = "SIMON7_POSTAL_ADDRESS"  # a file in PROD_SECRETS_DIR, like SIMON7_MAIL_FROM; the runbook is docs/prod/settings.md
TEST_ADDRESS = "Example Address, Test City"  # dev, tests and staging; the prod start check refuses it
_TEST_WORDS = re.compile(r"example address|test city", re.IGNORECASE)
# An operator placeholder: `[UPPER CASE]` or `[UPPER CASE: a note]`, never a markdown link (legal_drafts.py).
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z0-9 ,_/&.'-]*(?::[^\]\n]*)?\](?!\()")
# page path -> draft file; the footer and the consent step link the first two
PAGES = {
    "privacy": "privacy-policy.md",
    "terms": "terms.md",
    "biometric": "biometric-retention.md",
    "dmca": "dmca.md",
    "accessibility": "accessibility.md",
    "sub-processors": "sub-processors.md",
}
TITLES = {"privacy": "Privacy policy", "terms": "Terms of use", "biometric": "Biometric data and retention",
          "dmca": "Copyright and takedown", "accessibility": "Accessibility", "sub-processors": "Who processes your data"}
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SAFE_HREF = re.compile(r"^(https://|mailto:|#|[a-z0-9][a-z0-9/_.-]*$)", re.IGNORECASE)


def _inline(text: str) -> str:
    out = html.escape(text, quote=True)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)

    def link(m: re.Match[str]) -> str:
        href = html.unescape(m.group(2))
        if not _SAFE_HREF.match(href) or href.lower().startswith(("javascript:", "data:")):
            return m.group(1)
        return f'<a href="{html.escape(href, quote=True)}">{m.group(1)}</a>'

    return _LINK.sub(link, out)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table(rows: list[str]) -> str:
    body = [r for r in rows if not re.match(r"^\|?\s*:?-{3,}", r.strip())]
    head, rest = _cells(body[0]), body[1:]
    out = ["<table><thead><tr>", *(f"<th>{_inline(c)}</th>" for c in head), "</tr></thead><tbody>"]
    for row in rest:
        out += ["<tr>", *(f"<td>{_inline(c)}</td>" for c in _cells(row)), "</tr>"]
    return "".join([*out, "</tbody></table>"])


def to_html(markdown: str) -> str:
    """The body HTML of a draft."""
    blocks: list[str] = []
    para: list[str] = []
    items: list[str] = []
    table: list[str] = []

    def flush() -> None:
        if para:
            blocks.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()
        if items:
            blocks.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>")
            items.clear()
        if table:
            blocks.append(_table(table))
            table.clear()

    for raw in _COMMENT.sub("", markdown).splitlines():
        line = raw.rstrip()
        heading = re.match(r"^(#{1,3}) (.+)$", line)
        if not line.strip():
            flush()
        elif heading:
            flush()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif line.lstrip().startswith("|"):
            if para or items:
                flush()
            table.append(line)
        elif line.startswith("- "):
            if para or table:
                flush()
            items.append(line[2:])
        elif items and line.startswith("  "):
            items[-1] += " " + line.strip()
        else:
            if items or table:
                flush()
            para.append(line.strip())
    flush()
    return "\n".join(blocks)


def address_problem(value: str | None) -> str | None:
    """Why `value` cannot be the address on a prod page, or None when it can. The reason never holds the value."""
    text = (value or "").strip()
    if not text:
        return "is missing or empty"
    if "\n" in text or "\r" in text:
        return "must be one line"
    if _TEST_WORDS.search(text):
        return "holds the test address"
    if PLACEHOLDER.search(text):
        return "holds a placeholder"
    return None


def postal_address() -> str | None:
    """The address to print: `TEST_ADDRESS` outside prod; in prod the setting, or None when it is unusable."""
    if not is_prod():
        return TEST_ADDRESS
    value = keys.read_key(ADDRESS_SETTING)
    return None if address_problem(value) else value


def fill(text: str) -> str:
    """A page's text with each token of TOKENS and the address token replaced by its value."""
    for token, value in TOKENS.items():
        text = text.replace(token, value)
    if ADDRESS_TOKEN in text:
        text = text.replace(ADDRESS_TOKEN, postal_address() or ADDRESS_TOKEN)
    return text


def render(name: str, folder: Path | None = None) -> bytes | None:
    """The whole page for `name` (a key of PAGES), or None when there is no such page, its draft is missing, or it
    names the postal address and there is none: a 404 is honest, a blank address on a copyright page is not."""
    file = PAGES.get(name)
    if file is None:
        return None
    try:
        text = ((folder or LEGAL_DIR) / file).read_text(encoding="utf-8")
    except OSError:
        return None
    if ADDRESS_TOKEN in text and postal_address() is None:
        return None
    title = html.escape(TITLES[name])
    page = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title} | Simon</title>\n"
        '<link rel="stylesheet" href="theme/tokens.css">\n<link rel="stylesheet" href="theme/legal.css">\n'
        '</head>\n<body class="legal">\n<a class="legal-skip" href="#legal-main">Skip to the text</a>\n'
        '<header class="legal-head"><a href="./#/">Back to Simon</a></header>\n'
        f'<main id="legal-main" class="legal-main" data-testid="legal-{html.escape(name)}">\n{to_html(fill(text))}\n</main>\n'
        '<footer class="legal-foot">' + " ".join(
            f'<a href="{k}">{html.escape(TITLES[k])}</a>' for k in PAGES) + "</footer>\n</body>\n</html>\n"
    )
    return page.encode("utf-8")
