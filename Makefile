.PHONY: check-5 test dummy-data output-examples

# Done-check for Part 5 (see README.md). Replace the stub with the real check:
# it must print a metrics JSON and exit 0 only when every threshold passes.
check-5:
	@echo "check-5: not implemented yet" && exit 1

test:
	uv run pytest -q

# Regenerate the synthetic labelled follower takes (fixtures/input/followers/).
dummy-data:
	python3 scripts/make_dummy_followers.py

# Regenerate the shipped analysis.json examples (fixtures/output/).
output-examples:
	uv run python scripts/make_output_examples.py
