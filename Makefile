.PHONY: check-5 dummy-data

# Done-check for Part 5 (see README.md). Replace the stub with the real check:
# it must print a metrics JSON and exit 0 only when every threshold passes.
check-5:
	@echo "check-5: not implemented yet" && exit 1

# Regenerate the synthetic labelled follower takes (fixtures/input/followers/).
dummy-data:
	python3 scripts/make_dummy_followers.py
