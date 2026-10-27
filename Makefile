.PHONY: check-6 demo-6

# Done-check for Part 6 (see README.md): prints one metrics JSON on stdout, logs on stderr,
# exits 0 only when every threshold passes. node_modules is installed on first use.
check-6:
	@[ -d node_modules/playwright ] || npm ci --prefer-offline --no-audit --no-fund >&2
	@node check/check6.mjs

# Demo package (AC-013): screenshots and walkthrough video in demo/. Not part of check-6.
demo-6:
	@[ -d node_modules/playwright ] || npm ci --prefer-offline --no-audit --no-fund >&2
	@node check/demo.mjs
