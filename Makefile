export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: setup test parts setup-parts videos chain serve dev check-7

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
check-7:
	@uv run python -m part7 check
