.PHONY: check-4 test animate fixtures contracts part3-squat meta-status

# src/ is the package root. Targets below assume `make` is run from the repo root.
export PYTHONPATH := src

# Done-check for Part 4. Prints metrics JSON and exits 0 only when every
# threshold passes for the exercise, dance, long and part3-squat fixtures and
# every fixture meets contracts/*.schema.json. No Meta API calls.
check-4:
	@python3 -m simon_anim.check

# Contract tests: schemas, fixtures, and what the loader rejects. Standard library only.
test:
	@python3 -m unittest discover -s tests

animate:
	@python3 -m simon_anim.animate

fixtures:
	@python3 scripts/generate_fixtures.py

# Rewrite contracts/*.schema.json from src/simon_anim/contract.py.
contracts:
	@python3 -m simon_anim.contract write

# Refresh fixtures/input/part3-squat from a Part 3 clone, then animate it.
# Usage: make part3-squat PART3=<path to simon-part-3-skeleton-consistency>
# Part 3 runs in its own clone and writes only into this repo.
PART3_SET := $(CURDIR)/fixtures/input/part3-squat
part3-squat:
	@test -n "$(PART3)" || { echo "set PART3=<path to a Part 3 clone>"; exit 2; }
	@mkdir -p "$(PART3_SET)"
	@cd "$(PART3)" && python3 -m part3 run --in fixtures/input/part2-single/pose3d.json \
		--out "$(PART3_SET)/skeleton.json" --view part4 --body part4-rig \
		--keyframes fixtures/conformance/inputs/keyframes.part1.json \
		--keyframes-out "$(PART3_SET)/keyframes.json"
	@python3 -m simon_anim.animate --set part3-squat

meta-status:
	@python3 -m simon_anim.meta_hooks status
