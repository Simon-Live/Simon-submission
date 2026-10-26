.PHONY: validate-fixtures fixtures

# P0 gate (see PLAN.md). Requires: python3 -m pip install jsonschema
validate-fixtures:
	python3 tools/validate_fixtures.py

# Regenerate the synthetic fixtures: push-up (reps; rep 2 flares) and arm phrase (music-timed sequence; pass 2 soft arms)
fixtures:
	python3 tools/make_pushup_fixture.py
	python3 tools/make_arm_phrase_fixture.py
