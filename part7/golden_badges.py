"""Badge JSON and a job summary from a run's JUnit and coverage files (TICKET-263, AC-4).

    python -m part7.golden_badges --junit junit.xml [--coverage coverage.xml] --out badges [--summary $GITHUB_STEP_SUMMARY]

Counts come from the files the run wrote, never from typed numbers. Each badge is a shields.io endpoint
document (`schemaVersion`, `label`, `message`, `color`). Nothing here changes the README; the badge URLs are
wired only after CI is green (docs/specs/golden-replay.md).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from xml.etree import ElementTree

EXIT_OK = 0
EXIT_UNUSABLE = 2


def junit_counts(path: Path) -> dict[str, int]:
    """`tests`, `failures`, `errors`, `skipped` summed over every testsuite of a JUnit file."""
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in total:
            total[key] += int(suite.get(key, "0"))
    return total


def coverage_percent(path: Path) -> float:
    """Line coverage in percent from a Cobertura `coverage.xml` (`line-rate` of the root)."""
    return round(float(ElementTree.parse(path).getroot().get("line-rate", "0")) * 100, 1)


def tests_badge(counts: dict[str, int]) -> dict[str, object]:
    bad = counts["failures"] + counts["errors"]
    passed = counts["tests"] - bad - counts["skipped"]
    message = f"{passed} passed" if not bad else f"{bad} failed, {passed} passed"
    return {"schemaVersion": 1, "label": "tests", "message": message, "color": "brightgreen" if not bad else "red"}


def coverage_badge(percent: float) -> dict[str, object]:
    color = "brightgreen" if percent >= 80 else "yellow" if percent >= 60 else "red"
    return {"schemaVersion": 1, "label": "coverage", "message": f"{percent:g}%", "color": color}


def summary_markdown(counts: dict[str, int], percent: float | None) -> str:
    rows = ["### Test run", "", "| Tests | Failures | Errors | Skipped | Coverage |", "|---|---|---|---|---|",
            f"| {counts['tests']} | {counts['failures']} | {counts['errors']} | {counts['skipped']} | "
            f"{'not measured' if percent is None else f'{percent:g}%'} |"]
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="part7.golden_badges")
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--coverage", type=Path, default=None)
    parser.add_argument("--out", required=True, type=Path, help="Folder for tests.json and coverage.json.")
    parser.add_argument("--summary", type=Path, default=None, help="Markdown file to append to ($GITHUB_STEP_SUMMARY).")
    args = parser.parse_args(argv)
    try:
        counts = junit_counts(args.junit)
        percent = coverage_percent(args.coverage) if args.coverage else None
    except (OSError, ElementTree.ParseError, ValueError) as exc:
        print(f"golden_badges: unreadable input: {exc}", file=sys.stderr)
        return EXIT_UNUSABLE
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "tests.json").write_text(json.dumps(tests_badge(counts)) + "\n", encoding="utf-8")
    if percent is not None:
        (args.out / "coverage.json").write_text(json.dumps(coverage_badge(percent)) + "\n", encoding="utf-8")
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(summary_markdown(counts, percent))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
