# Hand-made feet side files (TICKET-040, ADR-0015)

Two tiny files in the shape of Part 2's `pose3d.json`, made by hand for `tests/test_feet.py`. They are not copies of
Part 2's files. The canonical frame is x subject-left, y up, z anterior; the hips are at (+0.1, 0, 0) and (-0.1, 0, 0),
the ankles 0.9 m below them, the knees 0.45 m above the ankles, the feet flat 0.98 m below the hips.

`side-with-feet.json` holds four frames (`t_ms` 0, 33.333, 66.667, 100) and two people.

| Person | Frame | What the left foot does | `left_foot_rotation` | `left_ankle_inversion` | right foot |
|---|---|---|---|---|---|
| 0 | 0 | flat, along the pelvis's forward | 0 | 0 | 0 and 0 |
| 0 | 1 | turned out 20 degrees about the heel | 20 | 0 | 0 and 0 |
| 0 | 2 | heel `conf` 0.3 (below 0.5): not seen | NaN | NaN | 0 and 0 |
| 0 | 3 | rolled 20 degrees in about its long axis (outer edge down), shin leaning 20 degrees toward the midline | 0.577 | 20 | 0 and 0 |
| 7 | all | turned out 30 degrees about the heel | 30 | 0 | 0 and 0 |

Worked out by hand: the left foot's heel is (0.07, -0.98, -0.05); flat and forward its big toe is 0.2 m ahead and its
small toe (0.06, 0.15) from the heel in (x, z). A 20 degree toe-out turns the big toe vector (0, 0.2) to
(0.2 sin 20, 0.2 cos 20) = (0.068404, 0.187939) and the small toe vector to (0.06 cos 20 + 0.15 sin 20,
-0.06 sin 20 + 0.15 cos 20) = (0.107685, 0.120433); the hip line is along +x, so `foot_rotation` is
atan2(0.068404, 0.187939) = 20.

`ankle_inversion` is the roll of the foot plane about its long axis against world up; the shin is not read. The long
axis runs from the heel to the middle of the two toes, (0.03, 0.175) in (x, z), unit (0.16897, 0, 0.98562), and the
foot's outer edge is the up crossed with it, (0.98562, 0, -0.16897). Frame 3 turns the two toes about that axis through
the heel by 20 degrees, the outer edge going down. The big toe is 0.19712 along the axis and 0.03379 to the inner side
of it, so it moves to x = 0.07 + 0.19712 * 0.16897 - 0.03379 * cos 20 * 0.98562 = 0.07201, y = -0.98 + 0.03379 *
sin 20 = -0.96844 and z = 0.14966; the small toe is 0.15798 along the axis and 0.03379 to the outer side, and moves to
(0.12799, -0.99156, 0.10034). The plane's up now tilts 20 degrees to the outer side, so world up has cos 20 along it
and sin 20 against the outer edge, and `ankle_inversion` is atan2(sin 20, cos 20) = 20. The knee of frame 3 still sits
over a shin leaning 20 degrees toward the midline, (0.1 - 0.45 sin 20, -0.9 + 0.45 cos 20, 0) = (-0.053909, -0.477138,
0), and does not change the reading. The roll also moves the big toe 0.00201 m outward in x, so the heel to big toe
vector is (0.00201, 0.19966) in (x, z) and `foot_rotation` is atan2(0.00201, 0.19966) = 0.577. The right foot is the
left one mirrored in x and reads 0 and 0 throughout.

`side-no-feet.json` is the same four frames of person 0 with no `extra_joints`, as Part 2's cpu backend writes.
