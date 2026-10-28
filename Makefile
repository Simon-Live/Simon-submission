.PHONY: check-1 keyframes keyframes-fresh label test

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
# A video with saved SAM and Spark results is rebuilt from them at no cost.
keyframes: $(VENV)/.installed
	$(PY) -m keyframe_finder.from_video

# Send every video to SAM and Spark again, even when saved results exist.
keyframes-fresh: $(VENV)/.installed
	$(PY) -m keyframe_finder.from_video --fresh

# Local tests. These do not call the API.
test: $(VENV)/.installed
	$(PY) -m unittest keyframe_finder.mask_motion_test keyframe_finder.from_video_test keyframe_finder.evaluate_test keyframe_finder.quality_test

# Correct predicted keyframes in the browser. Saves fixtures/labels/<name>.json.
label: $(VENV)/.installed
	$(PY) -m keyframe_finder.label
