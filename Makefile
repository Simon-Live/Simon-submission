.PHONY: check-1 keyframes label

VENV := .venv
PY := $(VENV)/bin/python

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PY) -m pip install -r requirements.txt
	touch $(VENV)/.installed

# Prints a metrics JSON and exits 0 only when every threshold passes.
check-1: $(VENV)/.installed
	$(PY) -m keyframe_finder.evaluate

# Drop mp4 files in inbox/. Writes out/<name>/keyframes.json for each one.
keyframes: $(VENV)/.installed
	$(PY) -m keyframe_finder.from_video

# Correct predicted keyframes in the browser. Saves fixtures/labels/<name>.json.
label: $(VENV)/.installed
	$(PY) -m keyframe_finder.label
