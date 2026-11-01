export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: setup test parts setup-parts videos chain serve dev check-7 bench-faults

setup:
	uv sync

test:
	uv run pytest -q

# Parts 1 to 6 are git submodules under modules/ that track each part repo's main (ADR-0007).
# This moves them to the latest main, then runs each part's setup once per sha.
parts:
	git submodule sync --recursive
	git submodule update --init --remote --recursive
	uv run python -m part7 setup-parts

setup-parts:
	uv run python -m part7 setup-parts

videos:
	uv run python -m part7 videos fetch

chain:
	uv run python -m part7 chain

serve:
	uv run python -m part7 serve --host 127.0.0.1 --port 8727 --base-path /

dev:
	bin/dev.sh

# Done-check for Part 7 (docs/specs/check-7.md): prints one metrics JSON on stdout and
# exits 0 only when every gate passes (1 a gate failed, 2 a prerequisite is missing).
# Note: make itself exits 2 when this recipe fails; run `uv run python -m part7 check` for the exact code.
# `make check-7 TRACK_WORKER=1` runs the app under test with Part 2's warm tracker (default: cold, TICKET-129).
check-7:
	@SIMON7_CHECK7_TRACK_WORKER=$(TRACK_WORKER) uv run python -m part7 check

# Fault agreement on real takes (docs/specs/bench-faults.md); needs labels in bench/labels, exits 2 without them.
bench-faults:
	@uv run python -m part7.bench_faults
