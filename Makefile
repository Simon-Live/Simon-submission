.PHONY: check-5 test demo dummy-data output-examples test-contract contracts-check contracts-sync

# Done-check for Part 5 (see README.md): analyse every labelled take, print the metrics JSON,
# exit 0 only if good light passes at every angle (P >= 0.85, R >= 0.75, 0 faults on correct takes).
check-5:
	@uv run python -m part5.check

test:
	uv run pytest -q

# The 3D replay page and the analysis API on http://127.0.0.1:8735/ (docs/specs/viewer.md, AC-V11).
# Serves in the foreground from the committed fixtures; Ctrl-C stops it.
demo:
	uv run python -m part5 serve --port 8735

# Regenerate the synthetic labelled follower takes (fixtures/input/followers/).
dummy-data:
	python3 scripts/make_dummy_followers.py

# Regenerate the shipped analysis.json examples (fixtures/output/).
output-examples:
	uv run python scripts/make_output_examples.py

# Input contract (CONTRACT.md): load every Part 3 and Part 4 file through part5.io and validate it.
test-contract:
	uv run pytest -q tests/test_contract.py

# Compare the copies under contracts/ and fixtures/input/contract/ with Parts 3 and 4 (exit 1 on drift).
# PART3_DIR / PART4_DIR point at local checkouts; otherwise the repos are cloned from GitHub.
contracts-check:
	uv run python scripts/sync_contracts.py --check

# Refresh those copies and contracts/sources.lock.json from Parts 3 and 4.
contracts-sync:
	uv run python scripts/sync_contracts.py

# Contract check: the five schemas are valid, every committed fixture validates and loads through
# part5.io, and the golden analysis outputs rebuild byte for byte. Prints a JSON summary and exits 0
# only when it has no failures.
.PHONY: check-5-contract
check-5-contract:
	@uv run python -m part5.contract --check

# Real takes (docs/specs/real-takes.md): Part 3's kit against part3-squat, Part 2's mismatch takes and, once
# delivered, the stock takes. Writes out/report-real/report.json. Reported, never gated.
.PHONY: report-real
report-real:
	@uv run python -m part5 report-real

# Opt-in live call to Muse Spark through Baseten (one fixed fault record, needs the key file). Exit 0 only
# when a valid line came back. Never part of test, check-5 or the publish check.
.PHONY: smoke-muse-spark
smoke-muse-spark:
	META_LIVE=1 uv run python -m part5.phrasing.smoke

# Held-out set for one attempt (docs/specs/calibration.md, ADR-0003): run once per seed, in the order
# 29, 31, 37, after the attempt's freeze commit. Replaces fixtures/input/heldout/. SEED is required.
.PHONY: heldout-data
heldout-data:
	@case "$(SEED)" in \
	  29|31|37) ;; \
	  "") echo "heldout-data: SEED is required (29, then 31, then 37): make heldout-data SEED=29" >&2; exit 2 ;; \
	  *) echo "heldout-data: SEED=$(SEED) is not a held-out seed (29, 31, 37); seed 5 is the tuning set" >&2; exit 2 ;; \
	esac
	python3 scripts/make_dummy_followers.py --seed $(SEED) --out fixtures/input/heldout --dropout-variant
