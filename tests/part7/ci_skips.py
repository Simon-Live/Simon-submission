"""Stated skips for the CI job (TICKET-244), loaded by tests/conftest.py.

Parts 1 to 6 are private repos: CI checks them out only when the PARTS_READ_TOKEN secret is set. Without them, a test
that reads or runs a part checkout skips with a reason naming the secret, and the run ends with one count line (also
written to $GITHUB_STEP_SUMMARY). On a GitHub runner, tests that need the GPU host or the staging host always skip.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from part7 import config

PARTS_NOTE = "the part repos are not checked out (CI checks out Parts 1 to 6 only when the PARTS_READ_TOKEN secret is set)"
ALL_PARTS = ("1", "2", "3", "4", "5", "6")

# Tests that read or run a real part checkout under modules/part-N. Key: node id or node id prefix (a file, or a test
# function with all its parameters). Value: the parts the test needs.
NEEDS_PARTS: dict[str, tuple[str, ...]] = {
    "tests/test_parts.py::test_p6_catalog_child_against_real_part6_clone": ("6",),
    "tests/test_parts.py::test_real_parts_2_to_6_handoffs_end_to_end": ("2", "3", "4", "5", "6"),
    "tests/test_spike_sam31_bodypart.py::test_decode_rle_round_trip": ("2",),
    "tests/part7/test_animation_format.py::test_part5_doctor_accepts_the_converted_sample": ("5",),
    "tests/part7/test_animation_format.py::test_real_part5_analyse_on_a_converted_sample": ("5",),
    "tests/part7/test_camera_paths.py::test_the_samples_are_what_the_tool_makes_for_the_fixture_result": ("2",),
    "tests/part7/test_camera_paths.py::test_build_writes_four_files_that_validate_and_validate_exits_0": ("2",),
    "tests/part7/test_animation_format.py::test_sample_without_conversion_is_what_part5_rejected": ("5",),
    "tests/part7/test_golden_pipeline.py": ("3", "4", "5", "6"),
    # docs/ARCHITECTURE.md names formats only the parts' contracts/ schemas hold
    "tests/part7/test_arch_check.py::test_the_published_doc_matches_the_code": ALL_PARTS,
    "tests/part7/test_arch_check.py::test_the_command_line_exits_0_on_the_real_doc": ALL_PARTS,
    "tests/part7/test_arch_check.py::test_the_copy_passes_before_anything_is_planted": ALL_PARTS,
    "tests/part7/test_arch_check.py::test_a_moved_symbol_fails_and_fix_moves_the_link": ALL_PARTS,
    "tests/part7/test_history_guard.py::test_the_pinned_part_5_word_file_loads_when_the_clone_has_it": ("5",),
    "tests/part7/test_mode_scoring.py::test_real_part5_native_profiles": ("5",),
    "tests/part7/test_near_miss_words.py": ("5",),
    "tests/part7/test_own_analysis_quality.py::test_pinned_part5_doctor_accepts_the_own_analysis": ("5",),
    "tests/part7/test_part5_history_contract.py": ("5",),
    # Part 5's contracts/replay.schema.json validates every served replay (tests/part7/support.py seeds it)
    "tests/part7/test_quota_jobs_replay.py::test_fixture_replay_is_valid": ("5",),
    "tests/part7/test_quota_jobs_replay.py::test_broken_replay_is_rejected": ("5",),
    "tests/part7/test_server.py::test_follow_job_serves_analysis_and_validated_replay": ("5",),
    "tests/part7/test_server.py::test_replay_that_fails_its_contract_is_422": ("5",),
    "tests/part7/test_model_only.py::test_the_served_results_carry_video_kept_false": ("5",),
    "tests/part7/test_track_resample_frames.py::test_frame_times_from_the_part_2_command_on_a_real_clip": ("2",),
    "tests/part7/test_track_resample_frames.py::test_resampled_count_equals_part_2_sampled_count": ("2",),
}

# Tests that need the GPU host or the staging host. A GitHub runner has neither, so there they always skip.
HOST_ONLY: dict[str, str] = {
    "tests/part7/test_animation_format.py::test_every_staging_library_animation_is_handled":
        "reads the staging catalog of the GPU host",
    "tests/part7/test_animation_format.py::test_part5_doctor_accepts_every_converted_staging_sample":
        "reads the staging catalog of the GPU host",
}

# Tests that read a workspace file .simon-publish keeps out of the client repo. They run where the file is present.
NEEDS_FILE: dict[str, str] = {
    # the live server's own files (prod/, docs/prod/, staging/), which stay out of this repo
    "tests/part7/test_byok_own_clients.py::test_the_cli_down_sh_runs_stops_every_client":
        "prod/down.sh",
    "tests/part7/test_mail_hardening.py::test_support_is_a_registered_inbound_address":
        "docs/prod/registry-block.yaml",
    "tests/part7/test_mail_probe.py::test_smoke_fails_on_a_failing_probe_and_says_when_it_did_not_run":
        "prod/smoke.py",
    "tests/part7/test_mail_webhook.py::test_the_key_file_is_one_prod_reads_and_the_how_to_names_the_clicks":
        "docs/specs/mail-delivery.md",
    "tests/part7/test_muse_prod.py::test_ac_mp7_prod_copy_and_hashes":
        "deploy/part1-requirements.txt",
    "tests/part7/test_no_limits.py::test_no_window_or_cap_setting_is_left_in_the_prod_config":
        "prod/compute.conf",
    "tests/part7/test_part1_stop.py::test_each_setup_keeps_its_working_time":
        "staging/env.sh",
    "tests/part7/test_private_default.py::test_d3_the_teacher_specs_say_what_prod_data_says":
        "docs/specs/prod-data.md",
    "tests/part7/test_records_licences.py::test_ac1_licence_texts_sit_beside_the_meshes":
        "web/mesh-demo/LICENSE-SAM.txt",
    "tests/part7/test_serverless_client.py::test_up_sh_asks_for_the_converter_at_this_version":
        "prod/up.sh",
    "tests/part7/test_serverless_client.py::test_up_sh_passes_every_whole_number_setting_of_compute_conf":
        "prod/up.sh",
    "tests/part7/test_serverless_client.py::test_real_take_measures_a_cold_and_a_warm_call_with_no_server":
        "prod/compute.conf",
    "tests/part7/test_serverless_client.py::test_deploy_sh_stamps_only_after_a_deploy_that_worked_and_keeps_tokens_out_of_argv":
        "prod/compute.conf",
    "tests/part7/test_serverless_client.py::test_up_refuses_a_release_whose_app_is_not_deployed_and_names_the_command":
        "prod/up.sh",
    "tests/part7/test_serverless_client.py::test_up_refuses_another_version_and_passes_the_right_one":
        "prod/up.sh",
    "tests/part7/test_serverless_client.py::test_a_checked_release_restarts_with_modal_down_and_another_does_not":
        "prod/up.sh",
    "tests/part7/test_serverless_client.py::test_up_does_not_ask_modal_under_byok":
        "prod/up.sh",
    "tests/part7/test_camera_paths.py::test_the_samples_validate": "docs/specs/camera-path-samples/orbit.json",
    "tests/part7/test_camera_paths.py::test_the_samples_are_what_the_tool_makes_for_the_fixture_result":
        "docs/specs/camera-path-samples/orbit.json",
    "tests/part7/test_camera_paths.py::test_a_path_without_take_time_plays_in_real_time":
        "docs/specs/camera-path-samples/push-in.json",
    "tests/part7/test_golden_pipeline.py::test_fixtures_are_on_the_publish_allowlist": ".simon-publish",
    "tests/part7/test_queue_lock.py::test_jobs_after_pid_reads_only_a_positive_pid": "staging/server-lib.sh",
    "tests/test_gpu_guard.py::test_staging_env_marks_the_server_as_staging": "staging/env.sh",
    "tests/test_eval_report.py::test_committed_doc_matches_and_rebuild_is_stable":
        "docs/audit/eval-public-2026-11/details.json",
    "tests/part7/test_camera_paths.py::test_a_broken_path_is_refused_with_a_plain_line":
        "docs/specs/camera-path-samples/push-in.json",
    "tests/part7/test_camera_paths.py::test_many_problems_are_summarised": "docs/specs/camera-path-samples/push-in.json",
    "tests/part7/test_camera_paths.py::test_a_real_time_path_longer_than_the_take_is_refused":
        "docs/specs/camera-path-samples/push-in.json",
}

GPU_OPT_IN_ENV = "SIMON7_TEST_GPU"
GPU_OPT_IN_REASON = ("real Part 2 on the GPU; set SIMON7_TEST_GPU=1 for the final validation run, only while staging "
                     "is idle")

_STASH = pytest.StashKey[dict[str, int]]()


def missing_parts() -> set[str]:
    """Parts whose checkout is absent or empty (a clone without `git submodule update --init` has empty folders)."""
    out = set()
    for n in ALL_PARTS:
        d = Path(config.part_dir(n))
        if not d.is_dir() or not any(d.iterdir()):
            out.add(n)
    return out


def on_github_runner() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _lookup(nodeid: str, table: dict[str, object]) -> object | None:
    for key, value in table.items():
        if nodeid == key or nodeid.startswith(key + "::") or nodeid.startswith(key + "["):
            return value
    return None


def skip_reason(nodeid: str, missing: set[str], github: bool) -> tuple[str, str] | None:
    """(kind, reason) when the test must skip here, else None. kind is "parts", "unpublished" or "host"."""
    need = _lookup(nodeid, NEEDS_PARTS)
    lacking = sorted(set(need or ()) & missing)
    if lacking:
        return "parts", f"needs modules/part-{', part-'.join(lacking)}: {PARTS_NOTE}"
    path = _lookup(nodeid, NEEDS_FILE)
    if path and not (config.REPO_ROOT / str(path)).is_file():
        return "unpublished", f"reads {path}, which .simon-publish keeps out of the client repo"
    why = _lookup(nodeid, HOST_ONLY)
    if github and why:
        return "host", f"GitHub runners have no GPU and no staging host; this test {why}"
    return None


def gpu_opt_in_skip(item_has_marker: bool, env: dict[str, str] | os._Environ[str] = os.environ) -> str | None:
    """TICKET-349: a `gpu_host` test launches real Part 2, which takes the host's shared GPU lock from live staging
    takes. It skips unless SIMON7_TEST_GPU=1."""
    if item_has_marker and env.get(GPU_OPT_IN_ENV) != "1":
        return GPU_OPT_IN_REASON
    return None


def summary_lines(counts: dict[str, int], missing: set[str]) -> list[str]:
    lines = []
    if missing:
        lines.append(f"Part repos not checked out (PARTS_READ_TOKEN not set): {counts.get('parts', 0)} tests skipped "
                     "that need them")
    if counts.get("unpublished"):
        lines.append(f"Workspace files not in the client repo: {counts['unpublished']} tests skipped that read them")
    if counts.get("gpu_opt_in"):
        lines.append(f"GPU host tests not run (opt-in, SIMON7_TEST_GPU=1 for the final validation run): "
                     f"{counts['gpu_opt_in']}")
    if counts.get("host"):
        lines.append(f"GPU and staging host tests skipped on the GitHub runner: {counts['host']}")
    return lines


def configure(cfg: pytest.Config) -> None:
    cfg.stash[_STASH] = {"parts": 0, "unpublished": 0, "host": 0, "gpu_opt_in": 0}
    cfg.addinivalue_line("markers", "parts(*nums): the test reads or runs the real part checkouts (modules/part-N)")
    cfg.addinivalue_line("markers", "gpu_host(): the test launches real Part 2 on the GPU; skipped unless SIMON7_TEST_GPU=1")


def setup(item: pytest.Item) -> None:
    need = item.get_closest_marker("parts")
    nodeid = item.nodeid
    if need is not None and _lookup(nodeid, NEEDS_PARTS) is None:
        NEEDS_PARTS[nodeid] = tuple(str(n) for n in need.args) or ALL_PARTS
    hit = skip_reason(nodeid, missing_parts(), on_github_runner())
    if hit:
        item.config.stash[_STASH][hit[0]] += 1
        pytest.skip(hit[1])
    # after the CI reasons, so a test skipped there for the host is counted once, as "host", and never as opt-in too
    opt_in = gpu_opt_in_skip(item.get_closest_marker("gpu_host") is not None)
    if opt_in:
        item.config.stash[_STASH]["gpu_opt_in"] += 1
        pytest.skip(opt_in)


def terminal_summary(reporter: pytest.TerminalReporter) -> None:
    lines = summary_lines(reporter.config.stash.get(_STASH, {}), missing_parts())
    for line in lines:
        reporter.write_line(line)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if lines and target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("".join(f"{line}\n" for line in lines))
