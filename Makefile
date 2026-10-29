.PHONY: check-5 test dummy-data output-examples test-contract contracts-check contracts-sync

# Done-check for Part 5 (see README.md): analyse every labelled take, print the metrics JSON,
# exit 0 only if good light passes at every angle (P >= 0.85, R >= 0.75, 0 faults on correct takes).
check-5:
	@uv run python -m part5.check

test:
	uv run pytest -q

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
