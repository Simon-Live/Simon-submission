.PHONY: validate-fixtures fixtures test

# P0 gate (see PLAN.md). Requires: python3 -m pip install jsonschema
validate-fixtures:
	python3 tools/validate_fixtures.py

# Contract tests for schemas + tools/measures.py (stdlib unittest, no extra deps)
test:
	python3 -m unittest discover -s tests

# Regenerate the synthetic fixtures: push-up (reps; rep 2 flares) and arm phrase (music-timed sequence; pass 2 soft arms)
fixtures:
	python3 tools/make_pushup_fixture.py
	python3 tools/make_arm_phrase_fixture.py
