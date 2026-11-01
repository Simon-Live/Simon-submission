# Contract fixtures: copied from Parts 3 and 4

Byte-for-byte copies of the files Parts 3 and 4 publish for Part 5. Only the shared files are used; no upstream code.
`contracts/sources.json` says what is copied from where, and `contracts/sources.lock.json` records the upstream
commit and sha256 of each file. Refresh with `make contracts-sync`; `make contracts-check` exits 1 on drift.

| Path | Source |
| --- | --- |
| `part3/followers/<take>/skeleton.json`, `part3/followers/labels.json` | `moalborati/simon-part-3-skeleton-consistency` `fixtures/conformance/followers/` (part5 view, 15 takes: front, 45 and side, each correct plus four faults) |
| `part3/view-part4/skeleton.json` | Part 3 `fixtures/conformance/golden/view-part4-every-10/skeleton.json` (`simon.skeleton.v1`) |
| `part3/native/skeleton.json` | Part 3 `fixtures/conformance/followers/squat_front_correct/skeleton.native.json` (native view; Part 5 rejects it) |
| `part4/exercise/animation.json` | `moalborati/simon-part-4-animate-keyframes` `fixtures/output/exercise/animation.json` |

## Not a copy: Part 7's no-person analysis

`part7/analysis.no-person.json` is written by hand from the document Part 7 described in moalborati/simon#61 (TICKET-048):
the analysis Part 7 makes itself when Part 2 finds nobody in a take. It is not a byte copy of a Part 7 file and is not in
`contracts/sources.lock.json`; replace it with Part 7's own file when Part 7 sends one. `make check-5-contract` validates
it against `contracts/analysis.schema.json` and loads it through `part5.output`; `tests/test_part7_no_person.py` also runs
`part5 doctor --for part7` on it.

`tests/test_contract.py` loads every file here through `part5.io.load_clip` and validates it against `contracts/`.
See `CONTRACT.md`.
