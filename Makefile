export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: setup test pin repin setup-parts videos chain serve dev check-7

setup:
	uv sync

test:
	uv run pytest -q

pin:
	uv run python -m part7 pin --materialize

repin:
	uv run python -m part7 pin --update --materialize
	uv run python -m part7 setup-parts
	$(MAKE) chain

setup-parts:
	uv run python -m part7 setup-parts

videos:
	uv run python -m part7 videos fetch

chain:
	uv run python -m part7 chain

serve:
	uv run python -m part7 serve --host 127.0.0.1 --port 8727 --base-path /

dev:
	bin/dev.sh

# Done-check for Part 7 (docs/specs/check-7.md): prints one metrics JSON on stdout and
# exits 0 only when every gate passes (1 a gate failed, 2 a prerequisite is missing).
check-7:
	@uv run python -m part7 check
