# Where these files come from

These six files are Part 4's own shipped data, copied byte for byte. No code was copied.

- Repo: simon-part-4-animate-keyframes
- Commit: 9f4c073
- Use: `fixtures/make_catalog.py` builds the catalog entries `part4-squat` and `part4-step-touch`
  from them, and `tests/part6/test_part4_entries.py` checks them against the hashes below.

| File here | Path in Part 4 | SHA-256 |
|---|---|---|
| `exercise/keyframes.json` | `fixtures/input/exercise/keyframes.json` | `070e5427f73401a36ef74636592a144ca0b14cd89d9df29638521cea73986cd9` |
| `exercise/skeleton.json` | `fixtures/input/exercise/skeleton.json` | `b16729e3ed06fe9700d9f5567e1963b83a7c26bcfec99e74dcc8101ef9aed1b8` |
| `exercise/animation.json` | `fixtures/output/exercise/animation.json` | `ddd896598cb41af3808f7f280438bcd1a421aa667c9ccfbad8e3cbc4c17ddc4a` |
| `dance/keyframes.json` | `fixtures/input/dance/keyframes.json` | `ea21629dc708a53a33d6a0cd25a2ea330d4119df707fa0f47563a60204f1baf4` |
| `dance/skeleton.json` | `fixtures/input/dance/skeleton.json` | `e9b6dd32b8287d3cabb632c49a2836a705a758e633150536ad8306a121a3c9fa` |
| `dance/animation.json` | `fixtures/output/dance/animation.json` | `039213b9c43c42349f70f05a4b0ff93c9036e2f3d05963e495ce52e967c63fdf` |

The exercise set is a three second squat. The dance set is a four second step-touch.

To refresh them, copy the same six paths from a newer Part 4 checkout, update the commit and the
hashes here, and rerun `python3 fixtures/make_catalog.py`.
