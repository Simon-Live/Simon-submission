export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: setup test test-gpu parts setup-parts parts-smoke parts-gate videos chain serve dev check-7 bench-faults bench-bodies-eval eval-report eval-report-check

setup:
	uv sync

test:
	uv run pytest -q

# The final validation run only (TICKET-349, docs/specs/gpu-host-tests.md): includes the `gpu_host` tests that launch
# real Part 2 on the GPU and take the host's shared lock. Run it only while staging is idle.
test-gpu:
	SIMON7_TEST_GPU=1 uv run pytest -q

# Parts 1 to 6 are git submodules under modules/ that track each part repo's main (ADR-0007).
# This moves them to the latest main, then runs each part's setup once per sha. It does not go through the staging
# parts gate: staging/up.sh runs it only on a first install or with SIMON7_PARTS_GATE=off, and otherwise adopts the
# gate-validated shas (`part7 parts-adopt`, TICKET-192).
parts:
	git submodule sync --recursive
	git submodule update --init --remote --recursive
	SIMON7_MODULES_DIR="$${SIMON7_BASE_MODULES_DIR:-$(CURDIR)/modules}" uv run python -m part7 setup-parts

# Sets up the base clones, never the module tree a staging build serves from (TICKET-329).
setup-parts:
	SIMON7_MODULES_DIR="$${SIMON7_BASE_MODULES_DIR:-$(CURDIR)/modules}" uv run python -m part7 setup-parts

# The fast Part 7 tests that exercise the part contracts and adapters (about half a minute); the staging parts gate
# runs them against a moved part before staging adopts it (docs/specs/staging.md). check-7 is left to the publish.
parts-smoke:
	uv run pytest -q $(shell uv run python -c "from part7.parts_gate import SMOKE_TESTS; print(' '.join(SMOKE_TESTS))")

# Check any moved part main in a throwaway worktree (exit 0 green or nothing moved, 1 red, 3 skipped).
parts-gate:
	uv run python -m part7 parts-gate

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
# make itself exits 2 whenever a recipe fails, so the exact code (1 gate failed, 2 missing or deferred) is also
# written to $(CHECK_RC_FILE) when set; scripts/simon-publish.sh reads it (TICKET-188).
# `make check-7 TRACK_WORKER=1` runs the app under test with Part 2's warm tracker (default: cold, TICKET-129).
check-7:
	@SIMON7_CHECK7_TRACK_WORKER=$(TRACK_WORKER) uv run python -m part7 check; rc=$$?; \
	  if [ -n "$(CHECK_RC_FILE)" ]; then echo $$rc > "$(CHECK_RC_FILE)"; fi; exit $$rc

# Fault agreement on real takes (docs/specs/bench-faults.md); needs labels in bench/labels, exits 2 without them.
bench-faults:
	@uv run python -m part7.bench_faults

# MHR synthetic body bench, evaluation half (docs/specs/mhr-bench.md): reads bench/bodies/manifest.json and the Part 2 to 5
# job outputs the render lane produced, writes bench/results/<date>/mhr-bench.json; exits 2 without them.
bench-bodies-eval:
	@uv run python -m part7.mhr_bench

# docs/evaluation.md and the README tables, rebuilt from bench/results/ (docs/specs/eval-report.md). No GPU, no key.
# eval-report-check exits 1 naming the first differing line; CI runs it.
eval-report:
	@python3 tools/eval_report.py

eval-report-check:
	@python3 tools/eval_report.py --check
