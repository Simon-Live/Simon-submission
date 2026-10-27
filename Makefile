.PHONY: check-4 animate fixtures meta-status

# src/ is the package root. Targets below assume `make` is run from the repo root.
export PYTHONPATH := src

# Done-check for Part 4. Prints metrics JSON and exits 0 only when every
# threshold passes for the exercise and dance fixtures. No Meta API calls.
check-4:
	@python3 -m simon_anim.check

animate:
	@python3 -m simon_anim.animate --set exercise --set dance

fixtures:
	@python3 scripts/generate_fixtures.py

meta-status:
	@python3 -m simon_anim.meta_hooks status
