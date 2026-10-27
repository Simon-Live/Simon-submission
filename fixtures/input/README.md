# Input fixtures

Synthetic files that stand in for the shared files Part 6 stores with each entry. A procedural
10 s squat of one person (3 repetitions, fixed bone lengths), written by `make_fixtures.py`; no
recording or model produced them.

| File | Written upstream by | Shape |
|---|---|---|
| `keyframes.json` | Part 1 | Part 1's published "## Output" shape, 3 reps of start, bottom, top |
| `skeleton.json` | Part 3 | Part 3's output contract, schema `simon.skeleton/1`: header (units, frame, joints, 18 bones, standard, bone lengths, person, mirror, input hash) and frames at 15 fps |
| `animation.json` | Part 4 | provisional, schema `simon.animation/1`: the skeleton's units, frame and joints, frames at 30 fps, `interpolated: true` on odd frames |

Joints: the canonical 17, subject's left and right. Frame: origin at the hip midpoint, x subject's
left, y up, z anterior, metres. The skeleton follows Part 3's published contract, including its 18 bone names and
order; the bone lengths are this fixture's synthetic body, not Part 3's standard body. The animation
shape stays provisional until Part 4 publishes its own. The even animation frames carry the same
`t_ms` as the skeleton frames. Part 6 reads only joints, `t_ms` and `fps`, so extra fields load
unchanged.

Regenerate: `python3 fixtures/input/make_fixtures.py`.
