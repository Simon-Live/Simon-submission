# Spec: SAM 3D Body mesh sequence (mesh3d.json + mesh3d.bin)

> Copy of `docs/specs/mesh3d.md` from the maintainers' working repo at `843de10`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Implemented
Date: 2026-10-31
Linked PRD: none. Requirements source: Simon rubric audit 2026-10-31 (`simon-part-7/docs/audit/rubric-2026-10-31/meta-ai.md`
item 2). Part 2 ticket: TICKET-048, requested by simon-part-7 TICKET-143 and integrated from `lane/rubric-mesh`
(2e0f6b4). Parent spec: `docs/design/specs/backends-gpu-cpu.md`.
Request Type: feature-mod
Risk Level: routine (a new optional output behind a flag; no existing output changes)
Files: `part2/mesh3d.py`, `part2/body3d.py`, `part2/backends/gpu_sam3db.py`, `part2/backends/cpu_sam3db.py`,
`part2/cli.py`, `part2/mesh_stream.py`, `part2/doctor.py`, `part2/contract.py`, `part2/stamp.py` (the NOT_OUTPUT_CODE entry),
`contracts/mesh3d.schema.json`, `tests/test_mesh3d.py`, `tests/test_mesh_stream.py`, `tests/test_stamp.py`, `tests/test_worker_cli_integration.py`.
ADRs: ADR-0002 (backends), ADR-0005 (licences: the SAM License row and the MHR row).

## Overview
SAM 3D Body returns a full MHR body mesh for every person in every frame, and Part 2 kept only 23 points of it.
`part2 run --mesh` now also writes `mesh3d.json` (a small JSON header) and `mesh3d.bin` (the payload) next to
`pose3d.json`. The mesh is decimated once per run to about `--mesh-vertices` vertices (default 2500) by vertex
clustering on the first person-frame; every frame reuses that one plan, so the faces are written once and each
person-frame is only its vertex positions. Positions are in the pose3d canonical frame of that person and frame
(origin hip midpoint, x the subject's left, y up, z forward, metres), computed from the model's own 17 joints with
`part2.canonical.frame_axes`, and stored as little-endian int16 at 0.1 mm. Without `--mesh` nothing changes.

## Why This Is Wrong (Dissent-First)
- A binary payload is new for Part 2, whose contract tooling reads JSON. The header is JSON and goes through the
  same schema checker; only the vertex payload is binary, as glTF does, because JSON numbers would triple the size.
- Vertex clustering from one reference frame can merge vertices of two limbs that touch in that frame. Clusters
  are split into connected components of the mesh inside each voxel, so touching limbs never share a vertex.
- The mesh frame comes from the model's raw joints, while `--smooth` moves the pose3d joints over time. The mesh is
  not smoothed, so the two can differ by the smoothing; that offset has not been measured. `--refine` is refused with
  `--mesh`: its focal rung re-runs `body3d.estimate` without the collector, so a mesh built beside it would come from
  a different model run than `pose3d.json` (AC-M06). What was measured, without either option, is the distance of
  each joint to its nearest mesh vertex (AC-NFR-M01). Part 7 runs neither option.

## Acceptance Criteria
### AC-M01: off by default
Given `part2 run` without `--mesh`, then no mesh3d file is written and every other output is unchanged.
### AC-M02: flag writes the pair
Given `part2 run --mesh` on a SAM 3D Body backend (`gpu`, `cpu-sam3db`), then `mesh3d.json` and `mesh3d.bin` are
written next to `pose3d.json` after it, and the header validates against `contracts/mesh3d.schema.json`.
### AC-M03: decimation
The decimated vertex count is at most `--mesh-vertices` and at least half of it (when the source mesh has more),
every face index is below the vertex count, no face repeats a vertex, and no face appears twice.
### AC-M04: same frame as pose3d
For a mesh built from joints J and vertices V in camera space, the stored vertices equal
`canonical.to_canonical(decimated V, R, t)` with `R, t = canonical.frame_axes(J)` within 0.1 mm.
### AC-M05: frames and people
The header lists every input frame with its `frame` and `t_ms`, and each person with a byte offset into the bin. A
person whose hips are degenerate is left out of that frame, as pose3d does.
### AC-M06: refusals
`--mesh` with the `cpu` backend exits 2 naming the SAM 3D Body backends; `--mesh-vertices` below 100 exits 2, and 0
and negative counts are below 100 (0 is a count, not "unset"); `--mesh-vertices` without `--mesh` exits 2; `--mesh`
with any `--refine` other than `none` exits 2 with `part2: --mesh cannot be combined with --refine (the mesh comes
from the unrefined run)`. Nothing is written, no frame is ingested and nothing is removed: a pair already in `--out`
stays where it is. The same holds for every command refused before `--input` is opened: the collector is built, and
its count checked, before anything is unlinked, and the `--tracks` file is read and checked against `--ids` before the
unlink too, so a `--tracks` file that cannot be read, is not a valid tracks file or lacks an `--ids` entry (exit 1)
also leaves the old pair in place. The old pair is removed just before the input is read, so a failure from that point
on can follow the removal: exit 1 for an `--input` that cannot be read, an `--fps` of 0 or less or a `--tracks` file
made for other frames, exit 2 for an unknown `--tracker` in `--mode multi`. The `pose3d.json` of the earlier run is then left without a
mesh pair, never with a mismatched one (`tests/test_mesh3d.py`: the refusal and bad `--tracks` tests, and the
unreadable-input, `--fps` 0, other-frames `--tracks` and unknown-tracker tests).
### AC-M07: doctor
`part2 doctor mesh3d.json` names kind mesh3d (found by its `format` field, reported as "by its format field"), checks
the header against `contracts/mesh3d.schema.json` first and then the bin (size, sha256, offsets, face indices) and
exits 0 when valid, 1 when not, with the same report as for `pose3d.json`: `schema: breaks part2.mesh3d/2026-10-31 at
mesh3d.frames: expected array, got int`, and the same fields under `--json`. Any malformed header gives that report and
exit 1, never a traceback: `frames` or `people` that is not an array, a frame or person that is not an object, a
missing key, a bin that cannot be read. The people and frame counts in the report count only what has the right type.
`--for part3|part5|part6` says that consumer does not read it (exit 1).
### AC-M08: integrity
`mesh3d.read(path)` refuses a bin whose size or sha256 differs from the header, and a `bin` name with a path part.
### AC-M09: limb labels
Every vertex carries the index of its nearest canonical joint on the first person-frame, so a viewer can tint the
vertices of a faulty joint without the pose3d file; `validate` refuses a label outside `names`.
### AC-M10: cpu-sam3db is supported
Given `part2 run --mesh --backend cpu-sam3db`, then the pair is written exactly as on `gpu`. Decision (TICKET-048):
the variant runs the same SAM 3D Body, so the MHR vertices are in the same `process_one_image` output and
`cpu_sam3db.Backend.estimate` passes the collector to `body3d.estimate` as `gpu_sam3db.Backend.estimate` does (one
helper, `gpu_sam3db.mesh_kwargs`); refusing it would only add a rule. The `warm` timing of TICKET-046 and
`install_problem` are untouched. `mesh3d.BACKENDS` is the set of registry backends whose `estimate` takes `mesh`
(a test compares the two).
### AC-M11: no person found
Given `--mesh` and a run in which no frame has a person, then the run exits 4 with the unchanged
`part2: no person found in <n> frames` line (TICKET-047) and writes no `mesh3d.json` or `mesh3d.bin`. A pair left in
`--out` by an earlier run is removed once the options and the `--tracks` file have been accepted and before the first
frame is ingested, so none stays. AC-M06 says which failures can still follow that removal.
### AC-M12: tracker fallback
Given `--mode multi --mesh` and a Meta key the API refuses, then the bulk order moves on to the next tracker
that can run with its one stderr line (TICKET-045) as it does without `--mesh`, and the pair is written for the people
that tracker found. A named `--tracker api-sam31` still exits 1 and writes no mesh.
### AC-M13: warm worker
Given `part2 run --mesh [--mesh-vertices N] ... --worker SOCKET`, then both flags are part of the argv the worker
serves with the CLI's own `main`, and the pair appears beside `pose3d.json`; `--mesh` on the `cpu` backend through the
worker is exit 2 and no person found is exit 4, as in process.
### AC-M14: licence in every header
Every `mesh3d.json` header carries a non-empty `licence` that names the SAM License and Apache-2.0; the schema requires
the key and `validate` refuses a header without it. Licence text: "Licence" below.
### AC-M15: nothing of the mesh is committed
No mesh output (`mesh3d.json`, `mesh3d.bin`), no asset and no face list is committed to Part 2's tree or published.
`.gitignore` lists the two output names and a test checks that `git ls-files` holds neither.
### AC-M16: people found, no mesh collected
Given `--mesh` and a run that finds people but keeps no mesh vertex (every person's hips give no canonical frame, so
`Collector.add` keeps nothing), then `pose3d.json` (and `camera.json` in single mode) is written as without `--mesh`, no
pair is written, `part2: --mesh found no mesh vertices; no mesh3d pair written` is printed on stderr and the run exits
1. A run that asked for no mesh is unaffected. This differs from AC-M11, where nobody is found and the run exits 4.
### AC-M17: mirrored input
`--mirrored` flips nothing in Part 2: `pose3d.json` gets `"mirrored": true` over unmirrored joints, and the mesh is in the
same unmirrored frame (a run with and without `--mirrored` writes byte-identical `mesh3d.json` and `mesh3d.bin`). A
reader that mirrors the joints (Part 3 `--flip auto`) must mirror the mesh the same way: negate every vertex x, swap the
`left_` and `right_` names in `vertex_joint.names`, and swap two indices of each face so the winding is reversed too.
CONTRACT.md states the rule as it does for `extra_joints`.
### AC-M18: the bin is streamed
`Collector.write` hashes the bin with an incremental sha256 and writes it block by block; it never joins the faces,
the labels and every block into one bytes object (about 190 MB for 601 frames of 7 people at 2500 vertices, three
times the bin in memory before it streamed). The file, `bin_bytes` and `bin_sha256` are byte-identical to the joined
payload of earlier versions.
### AC-NFR-M01: size budget
At most 160 KB per second of video per person at 10 fps with the default 2500 vertices (int16: 15 KB per
person-frame), plus the faces once. Verification: test (`bytes_per_person_frame`) and the measured real run.

Measured in the TICKET-048 integration (RTX 5090 host, 2026-10-31; the first 15 frames of `fixtures/input/single/frames`,
3 s at 5 fps, one person; commands in the ticket's evidence record, outputs under the git-ignored `out/`):
- `--backend gpu --mesh`: 2432 of 18439 vertices, 4797 faces as uint16; `mesh3d.bin` 250,096 bytes (14,592 per
  person-frame, 31,216 for the faces and labels once), `mesh3d.json` 1,934 bytes; `part2 doctor` on both exits 0.
- Each of the 17 joints lay a mean 2.4 cm (median 2.0, largest 9.1) from its nearest mesh vertex over the 15
  person-frames of that unrefined, unsmoothed run, so the mesh and the joints share one frame. This is a consistency
  check, not an accuracy claim, and it is the only measurement of the two: neither `--smooth` nor `--refine` was
  measured with the mesh.
- `pose3d.json` joints of that run and of a run without `--mesh` differ by at most 0.5 mm; two runs without `--mesh`
  differ by the same amount, which is the GPU's run-to-run noise (the CPU test with the fake estimator is exact,
  `test_pose3d_and_camera_are_the_same_with_and_without_mesh`).
- `--backend cpu-sam3db --mesh` on the first 3 frames: 2444 vertices, doctor exit 0 (63 s per frame, 22 threads).

## API / Interface Contract
- `part2 run ... --mesh [--mesh-vertices N]` (`--mode single` or `multi`; `--backend gpu` or `cpu-sam3db`).
- `backend.estimate(frames_dir, out_path, boxes=None, mesh=None)` on the two SAM 3D Body backends; `mesh` is a
  `Collector` or None, and None leaves the call to `body3d.estimate` exactly as before the flag existed.
- `part2.mesh3d.Collector(target)`: `.frame(frame, t_ms)`, `.add(pid, verts_cam, faces, joints_cam) -> bool`,
  `.write(out_dir, model) -> (json_path, bin_path)`.
- `part2.mesh3d.plan(vertices, faces, target) -> Plan(labels, count, faces)`, `apply(plan, vertices)`.
- `part2.mesh3d.check_header(header)` (schema and frame order, no bin), `check_payload(header, payload)` (size, sha256,
  layout), `validate(header, payload)` (both), `read(path) -> (header, payload)`, `diagnose(path, doc, consumer)`.
- `part2/mesh3d.py` is in `part2.stamp.NOT_OUTPUT_CODE`: the import walk reaches it through `contract.py` and
  `doctor.py`, it writes no scored file, and no scored path imports it, so it is in no scored stamp's `code_files`.
- Header fields: `format` `part2.mesh3d/2026-10-31`, `frame_of_reference`, `model`, `licence`, `bin`,
  `bin_bytes`, `bin_sha256`, `source_vertex_count`, `vertex_count`, `face_count`,
  `faces {offset, dtype uint16|uint32}`, `vertices {dtype int16, unit_m 0.0001}`, `vertex_joint {offset, names}`,
  `clipped`,
  `frames [{frame, t_ms, people [{id, offset}]}]`.
- Bin: faces `face_count x 3` little-endian at `faces.offset` (0), then `vertex_count` uint8 labels at
  `vertex_joint.offset` (index into `vertex_joint.names`, the 17 canonical joints: each vertex's nearest joint on the
  first person-frame), each padded to 4 bytes, then one block of `vertex_count x 3` int16 per person-frame.

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|---|---|---|---|
| `--mesh` with `--backend cpu` | exit 2 | `part2: --mesh needs SAM 3D Body (--backend gpu or cpu-sam3db)` | AC-M06 |
| `--mesh-vertices` < 100 (0 and negative included) | exit 2 | `part2: --mesh-vertices must be at least 100` | AC-M06 |
| `--mesh` with `--refine` other than `none` | exit 2 | `part2: --mesh cannot be combined with --refine (the mesh comes from the unrefined run)` | AC-M06 |
| `--mesh-vertices` without `--mesh` | exit 2 | `part2: --mesh-vertices applies to --mesh only` | AC-M06 |
| `--mesh` and no person in any frame | exit 4, no mesh file | `part2: no person found in <n> frames` (unchanged) | AC-M11 |
| `--mesh`, people found, no mesh vertex kept | exit 1, `pose3d.json` kept, no mesh file | `part2: --mesh found no mesh vertices; no mesh3d pair written` | AC-M16 |
| mesh3d.json with a malformed header or an unreadable bin | doctor exit 1 with the `schema: breaks` line | `mesh3d.frames: expected array, got int` | AC-M07 |
| bin size or sha256 mismatch | ContractError, doctor exit 1 | `mesh3d.bin: ...` | AC-M07, AC-M08 |
| a coordinate beyond +-3.2767 m from the hips | clamped to +-3.2767 m (32767 units), counted in `clipped`, never wrapped | | AC-M02 |

## Edge Cases
- Source mesh smaller than the target: kept whole (AC-M03).
- A frame with no person: listed with an empty people list (AC-M05).
- No person in any frame: no mesh is written and the run exits 4 (AC-M11); a stale pair is already gone.
- People found but no hips give a canonical frame: exit 1, `pose3d.json` kept (AC-M16).
- A coordinate exactly at 3.2767 m is kept and not counted; one unit (0.1 mm) past it is clamped and counted.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|---|---|---|---|
| Performance | decimation plan | once per run, numpy only | AC-M03 |
| Scalability | file size | AC-NFR-M01 | AC-NFR-M01 |
| Security | bin name | no path part (schema pattern and read check) | AC-M08 |
| Others | N/A: a file format with no UI, users or service | | |

## Negative Requirements
- MUST NOT change any output when `--mesh` is absent. Why: every consumer and gate reads them.
- MUST NOT add a required dependency: numpy only.
- MUST NOT commit or publish a mesh output, an asset or a face list (AC-M15). Why: the faces derive from MHR and the
  pair from SAM 3D Body, whose licences ask for their texts to travel with any redistribution ("Licence", below).

## Compromises
### Vertex clustering instead of quadric decimation
Short-term: clustering, numpy only. Long-term: quadric decimation of the MHR rest mesh with a fixed vertex subset.
Trigger to revisit: visible faceting on the hands or face in the demo.

## Non-Requirements
- Hands and face detail, textures, normals (the viewer computes normals).
- Part 3 and Part 6 reading the mesh.

## Licence
- SAM 3D Body and the MHR model file Part 2 loads (`assets/mhr_model.pt` from the SAM 3D Body mirror, listed in
  ADR-0005 under the SAM License) come under the mirror's SAM License. MHR upstream (`facebookresearch/MHR`) is
  Apache-2.0. The header's `licence` field names both: "SAM 3D Body: SAM License (Meta, 2025-11-19); MHR body model:
  Apache-2.0 (facebookresearch/MHR)".
- A copy of the SAM License goes with any redistribution of the mesh. Apache-2.0 also requires its licence text and
  MHR's notice to go with any redistribution of the mesh faces, which derive from MHR (CONTRACT.md, "Licence" row).
- No mesh output, asset or face list is committed to Part 2's tree or published (AC-M15): the pair is written under
  the run's `--out` (git-ignored `out/` in a checkout), and `.gitignore` lists `mesh3d.json` and `mesh3d.bin`.

## Assumptions
- none new; MHR licence read from `facebookresearch/MHR` by the rubric-mesh session (ADR-0005, "read 2026-10-31").

## Implied Requirements Discovered
- The doctor must not mistake mesh3d.json for pose3d.json (both hold frames with people and t_ms).

## Delivery Verification Plan
### Device/Platform Strategy
| Platform | Tool | Viewport | Assigned To |
|---|---|---|---|
| CLI on the RTX 5090 host | `part2 run --mesh` on one Pexels clip, detached | n/a | rubric-mesh lane |
| Headless Chromium (Part 7 `web/mesh-demo.html`) | lane browser | 412x915 | rubric-mesh lane |
### Data
- No accounts. One real clip from Part 7 `videos/`; the output pair is measured (bytes per second, vertex count).
### Ratchet Initialization Plan
- N/A: no ratchet for an optional file.

## Dissent Review
Reviewed by: rubric-mesh lane (implementer, model: opus). Date: 2026-10-31
### Concern 1: binary payload
Challenge: JSON-only tooling. Impact: consumers cannot use the doctor. Mitigation: JSON header with sha256.
Resolution: ADDRESSED_IN_SPEC
### Concern 2: cross-limb merges
Challenge: clustering merges touching parts. Mitigation: per-voxel connected components. Resolution: ADDRESSED_IN_SPEC
### Concern 3: mesh and smoothed joints disagree
Challenge: `--smooth` moves joints only. Mitigation: documented; Part 7 does not smooth. Resolution: ACCEPTED_RISK
### Pre-Mortem
1. The file is too big for a phone. Likelihood L, Impact M, Mitigation: AC-NFR-M01 and `--mesh-vertices`.
2. The mesh drifts from the skeleton. Likelihood L, Impact M, Mitigation: AC-M04 test.
3. Licence objection. Likelihood L, Impact H, Mitigation: licence field in the header and ADR-0005 rows.

## Streaming (TICKET-284, requested by simon-part-7 TICKET-284)
`part2 run --mesh --mesh-stream` also writes `<out>/mesh3d.stream/` while SAM 3D Body runs, so a viewer can draw the
body pose by pose before the run ends. `--mesh-stream` without `--mesh` is exit 2. The folder holds `head.bin` (faces,
then vertex_joint labels, each padded to 4 bytes, written once with the first person), `chunk-NNNN.bin` (the int16
blocks of the frames finished since the last chunk, in block order) and `stream.json` (format
`part2.mesh3d-stream/2026-11-02`: `head` with vertex_count, face_count, faces and vertex_joint offsets and names;
`chunks` [{file, first_block, blocks}]; `block_bytes`; `frames` [{frame, t_ms, people [{id, block}]}] for the frames
finished so far; `frames_done`; `frames_total`; `done`). Every file is written under a dot name and renamed into place,
and the manifest is renamed last, so a chunk the manifest lists always exists and no reader sees a partial file.
Head bytes followed by the chunks in order are exactly `mesh3d.bin`. A person-frame with no usable hips has no block and
is not listed. The finished pair is written first and then the manifest gets `done: true`; the pair, `body3d.json`
and `camera.json` are byte-identical with and without the stream. A run clears an older stream in `<out>` at the same
point it clears an older pair.

- AC-M19: the pair, body3d.json and camera.json are byte-identical with and without `--mesh-stream`; a run without it writes no stream folder.
- AC-M20: head + chunks equals mesh3d.bin; the manifest ends `done` with frames_done = frames_total. While the run is going, `frames_total` is null: the frame count is set at the end, so body3d.py (a stamped file) carries no streaming hook; the collector ends each frame when the next one starts.
- AC-M21: after each frame the manifest lists only existing chunks and the frame count rises by one; `every=N` flushes in chunks, the first person-frame at once.
- AC-M22: no stream folder before the first person; every file is replaced atomically (a concurrent reader never fails to parse).
- AC-M23: an older stream is cleared by the next run; `--mesh-stream` alone is exit 2.
Tests: tests/test_mesh_stream.py. Measured cost: see the TICKET-284 evidence in simon-part-7.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|---|---|---|---|
| TICKET-048 size budget | AC-NFR-M01 | test_size_per_person_frame_meets_the_budget | passing |
| TICKET-048 mesh export | AC-M01 to AC-M05, AC-M09 | tests/test_mesh3d.py | passing |
| TICKET-048 review fixes (J3): doctor on any header, refusals that remove nothing, no mesh collected, mirrored, streamed write, clamp | AC-M06, AC-M07, AC-M16 to AC-M18 | tests/test_mesh3d.py, tests/test_stamp.py | passing |
| TICKET-048 doctor check | AC-M07 | test_doctor_rejects_a_tampered_bin_and_says_no_consumer_reads_it | passing |
| TICKET-048 integration with TICKET-045/046/047 (cpu-sam3db, exit 4, tracker fallback, warm worker) | AC-M10 to AC-M13 | tests/test_mesh3d.py, tests/test_worker_cli_integration.py | passing |
| TICKET-048 licence and nothing committed | AC-M14, AC-M15 | tests/test_mesh3d.py | passing |

## Test Scenarios
- AC-M01 → test_run_without_mesh_writes_no_mesh_file_and_removes_a_stale_pair,
  test_pose3d_and_camera_are_the_same_with_and_without_mesh,
  test_body3d_estimate_is_called_as_before_without_a_collector_and_gets_it_with_one,
  test_a_worker_run_without_mesh_removes_a_stale_pair_and_writes_none (worker file)
- AC-M02 → test_run_with_mesh_writes_the_pair_next_to_pose3d,
  test_coordinates_beyond_3_2767_m_clamp_and_are_counted_not_wrapped
- AC-M03 → test_plan_hits_the_target_and_keeps_faces_valid, test_small_mesh_is_kept_whole,
  test_touching_but_unconnected_parts_never_share_a_vertex
- AC-M04 → test_vertices_are_in_the_pose3d_canonical_frame
- AC-M05 → test_frames_and_people_are_listed_with_offsets_and_degenerate_hips_are_left_out,
  test_nothing_collected_writes_nothing
- AC-M06 → test_mesh_refusals_exit_2_and_write_nothing, test_a_refused_command_leaves_a_pair_already_in_out_untouched,
  test_refine_none_is_not_a_refinement_so_mesh_runs_with_it,
  test_a_run_refused_for_a_bad_tracks_file_leaves_the_old_pair_in_place
- AC-M07 → test_doctor_rejects_a_tampered_bin_and_says_no_consumer_reads_it,
  test_doctor_reports_a_malformed_header_like_it_does_for_pose3d_and_exits_1,
  test_doctor_on_a_valid_pair_exits_0_with_no_schema_line_and_counts,
  test_doctor_reports_a_missing_bin_as_a_schema_line_not_a_traceback
- AC-M08 → test_read_refuses_size_sha_and_path_mismatch,
  test_validate_refuses_a_face_index_past_the_vertices_and_an_offset_outside_the_bin
- AC-M09 → test_each_vertex_is_labelled_with_its_nearest_joint, test_validate_refuses_a_label_that_is_not_a_joint
- AC-M10 → test_cpu_sam3db_writes_the_same_pair_as_gpu_and_keeps_its_warm_timing,
  test_mesh_backends_are_exactly_the_registry_backends_whose_estimate_takes_mesh
- AC-M11 → test_no_person_found_with_mesh_exits_4_writes_no_mesh_and_leaves_no_stale_pair,
  test_no_person_found_by_the_tracker_with_mesh_exits_4_and_writes_no_mesh
- AC-M12 → test_mesh_in_multi_mode_follows_a_refused_credential_to_the_fallback_tracker,
  test_mesh_in_multi_mode_covers_only_the_listed_people, test_a_named_api_tracker_that_is_refused_exits_1_and_writes_no_mesh
- AC-M13 (tests/test_worker_cli_integration.py) → test_mesh_reaches_the_worker_and_writes_the_pair_the_in_process_run_writes,
  test_mesh_on_the_cpu_backend_is_exit_2_through_the_worker_and_it_keeps_serving,
  test_no_person_found_with_mesh_is_exit_4_through_the_worker_and_writes_no_mesh
- AC-M14 → test_every_header_carries_the_licence_naming_both_sources, test_a_header_without_a_licence_is_refused
- AC-M15 → test_git_tracks_no_mesh_output_and_no_mhr_asset, test_git_ignores_the_mesh_pair_wherever_it_lands
- AC-M16 → test_people_found_but_no_mesh_vertices_is_exit_1_with_pose3d_kept_and_no_pair,
  test_the_same_run_without_mesh_exits_0
- AC-M17 → test_mirrored_writes_the_flag_only_the_mesh_stays_in_the_same_unmirrored_frame_as_the_joints
- AC-M18 → test_the_streamed_bin_is_byte_identical_to_the_joined_payload, test_write_never_builds_the_whole_bin_in_memory
- Stamps (TICKET-048 B1) → tests/test_stamp.py::test_every_scored_mode_lists_the_shared_output_steps_and_its_closure_has_them,
  test_mesh3d_is_not_output_code_though_the_import_walk_reaches_it_through_the_doctor,
  test_no_module_joins_a_scored_closure_only_through_a_not_output_module
- AC-NFR-M01 → test_size_per_person_frame_meets_the_budget

## Deviations from PRD
| PRD item | Deviation | Reason |
|---|---|---|
| none | | |
