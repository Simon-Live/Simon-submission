"""Served legal pages that are still drafts (docs/specs/prod-hardening.md AC-PH13; prod verify a11y B10).

A page the app serves (`legal_pages.PAGES`, files in `docs/legal/`) is a draft while it holds an operator placeholder
(`[UPPER CASE]`, or `[UPPER CASE: a note]`, never a markdown link) or the "Needs lawyer review" banner. `prod_check`
refuses a prod start while any served page is a draft and names each file with its count. The crisis answer of both
Ask views (`history_ask_guard.CRISIS_TEXT`) is held to the same rule: while it names no crisis line, it is a draft. So
is each served copy file in `WEB_COPY` (the Me page's line on where Simon's Part 2 app comes from, a11y R5).

The one override: `SIMON7_LEGAL_DRAFTS=allow` together with `FIRM_PROD_ALLOW_LEGAL_DRAFTS=1`. Either alone is refused
in prod. With both, the start goes on and `warning` names the drafts on every start.

The postal address setting (`legal_pages.ADDRESS_SETTING`) is checked here too, and the override never waives it: a draft
page is still a page, a blank address is not (docs/specs/legal-pages.md AC-LP12).
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from part7 import legal_pages

PLACEHOLDER = legal_pages.PLACEHOLDER
BANNER = "Needs lawyer review"
ALLOW_ENV, ALLOW_VALUE = "SIMON7_LEGAL_DRAFTS", "allow"
PROD_ALLOW_ENV = "FIRM_PROD_ALLOW_LEGAL_DRAFTS"


def drafts(folder: Path | None = None) -> list[tuple[str, int, bool]]:
    """`(file name, placeholder count, has the banner)` of each served page that is a draft, in page order."""
    root = Path(folder) if folder is not None else legal_pages.LEGAL_DIR
    out = []
    for name in dict.fromkeys(legal_pages.PAGES.values()):
        try:
            text = (root / name).read_text(encoding="utf-8")
        except OSError:
            continue  # a missing page answers 404 (legal_pages.render); it serves no placeholder
        count, banner = len(PLACEHOLDER.findall(text)), BANNER in text
        if count or banner:
            out.append((name, count, banner))
    return out


CRISIS_NAME = "part7/history_ask_guard.py CRISIS_TEXT"
# Served copy with an operator line (a11y R5): the Me page's BYOK card says where a person gets Simon's Part 2 app.
WEB_COPY = ("web/modal-creds.js",)


def crisis_draft(text: str | None = None) -> list[tuple[str, int, bool]]:
    """`[(CRISIS_NAME, placeholder count, False)]` while the crisis answer holds a placeholder, else `[]`."""
    if text is None:
        from part7 import history_ask_guard  # here: read at call time, so the text in force is the one checked

        text = history_ask_guard.CRISIS_TEXT
    count = len(PLACEHOLDER.findall(text))
    return [(CRISIS_NAME, count, False)] if count else []


def copy_drafts(root: Path | None = None) -> list[tuple[str, int, bool]]:
    """`(file, placeholder count, False)` of each served copy file in WEB_COPY that still holds an operator placeholder."""
    from part7 import config  # here: tests point REPO_ROOT elsewhere

    base = Path(root) if root is not None else config.REPO_ROOT
    out = []
    for name in WEB_COPY:
        try:
            count = len(PLACEHOLDER.findall((base / name).read_text(encoding="utf-8")))
        except OSError:
            continue
        if count:
            out.append((name, count, False))
    return out


def _listing(found: list[tuple[str, int, bool]]) -> str:
    return ", ".join(f"{name} ({count} placeholders{', review banner' if banner else ''})"
                     for name, count, banner in found)


def _override(env: Mapping[str, str]) -> tuple[bool, bool]:
    return (env.get(ALLOW_ENV, "").strip().lower() == ALLOW_VALUE, env.get(PROD_ALLOW_ENV, "").strip() == "1")


def address_problems(env: Mapping[str, str]) -> list[str]:
    """The postal address setting in the secrets dir of `env`, named and never quoted. No secrets dir: `prod_check`
    has already refused that, so this adds nothing."""
    from part7 import prod_check  # here: legal_pages imports config, which imports prod_check

    secrets = prod_check.secrets_dir(env)
    if secrets is None or not secrets.is_dir():
        return []
    name = legal_pages.ADDRESS_SETTING
    try:
        value = (secrets / name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        value = ""
    reason = legal_pages.address_problem(value)
    return [f"the setting {name} in {prod_check.SECRETS_ENV} {reason}; /dmca and invite mail print it (docs/prod/settings.md)"] if reason else []


def problems(env: Mapping[str, str], folder: Path | None = None) -> list[str]:
    """What stops a prod start: drafts without the full override, or half an override."""
    allow, prod_allow = _override(env)
    out = []
    if env.get(ALLOW_ENV, "").strip() and not allow:
        out.append(f"{ALLOW_ENV} is set to something other than {ALLOW_VALUE}")
    if allow and not prod_allow:
        out.append(f"{ALLOW_ENV}={ALLOW_VALUE} is refused in prod unless {PROD_ALLOW_ENV}=1 is also set")
    found, crisis, copy = drafts(folder), crisis_draft(), copy_drafts()
    if copy and not (allow and prod_allow):
        out.append(f"served copy is a draft: {_listing(copy)}; fill each operator line")
    if found and not (allow and prod_allow):
        out.append(f"served legal pages are drafts: {_listing(found)}; fill every placeholder and remove the "
                   f"'{BANNER}' banner in docs/legal/")
    if crisis and not (allow and prod_allow):
        out.append(f"the crisis answer is a draft: {_listing(crisis)}; name the crisis line for each country served")
    out += address_problems(env)
    return out


def warning(env: Mapping[str, str], folder: Path | None = None) -> str | None:
    """The line logged on every prod start that serves drafts under the override, else None."""
    allow, prod_allow = _override(env)
    found = drafts(folder) + crisis_draft() + copy_drafts() if allow and prod_allow else []
    return f"warning: serving draft legal pages ({ALLOW_ENV}={ALLOW_VALUE}): {_listing(found)}" if found else None
