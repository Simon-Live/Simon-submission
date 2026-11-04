.PHONY: setup test run check-3 check-3-contract demo-data demo demo-stop

# Part 3 targets (docs/specs/part3-skeleton.md "Locked defaults").
PYTHON ?= python3
FLIP ?= auto
DEMO_PORT := 8733

setup:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest tests/part3 $(wildcard tests/staging) $(wildcard tests/neighbour) -q

# make run IN=<pose3d.json> OUT=<skeleton.json> [FLIP=auto|on|off]
run:
	$(PYTHON) -m part3 run --in "$(IN)" --out "$(OUT)" --flip "$(FLIP)"

# Done-check: prints the metrics JSON, exit 0 only when every threshold passes.
check-3:
	@$(PYTHON) -m part3.metrics

# Conformance kit: validates every golden and follower file against contracts/, rebuilds the kit byte for byte
# and checks every labelled fault is still visible. Prints a metrics JSON, exit 0 only when everything passes.
check-3-contract:
	@$(PYTHON) -m part3.conformance check

demo-data:
	$(PYTHON) -m part3.demo_data

# Serves the run app (part3.server) on 127.0.0.1:8733 in the background and returns; make demo-stop ends it.
demo:
	@if [ -f .demo.pid ] && kill -0 "$$(cat .demo.pid)" 2>/dev/null; then \
	  echo "demo already running: http://127.0.0.1:$(DEMO_PORT)/ (pid $$(cat .demo.pid))"; exit 0; fi
	@if ! $(PYTHON) -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$(DEMO_PORT))) else 1)"; then \
	  echo "port $(DEMO_PORT) is busy; stop what holds it or run make demo-stop"; exit 1; fi
	@mkdir -p out
	@setsid nohup $(PYTHON) -m part3.server --port $(DEMO_PORT) --base / > out/demo.log 2>&1 & echo $$! > .demo.pid
	@echo "demo: http://127.0.0.1:$(DEMO_PORT)/ (pid $$(cat .demo.pid)); stop with make demo-stop"

demo-stop:
	@if [ -f .demo.pid ]; then kill "$$(cat .demo.pid)" 2>/dev/null || true; rm -f .demo.pid; echo "demo stopped"; \
	else echo "demo not running"; fi
