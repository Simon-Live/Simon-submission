"""part6/jobs.py: parse_processor and the job queue (AC-C09)."""
import threading
import time

import pytest

from part6 import catalog, jobs, processor, validate
from part6.jobs import Busy, Jobs, parse_processor

GOOD = {"keyframes": {"k": 1}, "skeleton": {"s": 1}, "animation": {"a": 1}}


def rec(n=0, **changes):
    return dict({"id": f"job-{n}", "name": f"Move {n}", "category": "dance", "duration_ms": 2000,
                 "video_path": None}, **changes)


def until(check, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.005)
    return False


class Store:
    """A store callback that records its calls and returns a small manifest."""

    def __init__(self):
        self.calls = []
        self.parts = []
        self.error = None

    def __call__(self, recording, files, files_source, description, parts=None):
        self.calls.append((recording, files, files_source, description))
        self.parts.append(parts)
        if self.error:
            raise self.error
        return {"id": recording["id"], "name": recording["name"], "files_source": files_source,
                "description": description}


class Gate:
    """A processor that waits to be released, noting which recordings it saw."""

    def __init__(self, result=None):
        self.result = GOOD if result is None else result
        self.seen = []
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, recording, report):
        self.seen.append(recording["id"])
        self.started.set()
        assert self.release.wait(10), "the test never released the processor"
        return self.result


@pytest.fixture
def make(tmp_path):
    """make(run, **options) -> (Jobs, Store); every queue is closed at teardown."""
    made = []

    def build(run=None, **options):
        store = Store()
        queue = Jobs(tmp_path / "catalog", run, store=options.pop("store", store), **options)
        made.append(queue)
        return queue, store

    yield build
    for queue in made:
        queue.close(timeout=0.2)


def finish(queue, job_id, seconds=5):
    job = queue.wait(job_id, seconds)
    assert job["status"] == "done" or job["status"].startswith("failed:"), job
    return job


# parse_processor

def test_the_default_processor_is_the_mock():
    assert jobs.DEFAULT_PROCESSOR == processor.DEFAULT == "part6.processor:process"
    assert parse_processor(jobs.DEFAULT_PROCESSOR) is processor.process


def test_a_dotted_module_and_a_function_are_imported():
    run = parse_processor("fixtures.processors.part4_fake:fail")
    assert callable(run) and run.__name__ == "fail"


@pytest.mark.parametrize("spec", [
    "", "process", "part6.processor", "part6.processor:", ":process", "a:b:c", "1abc:fn",
    "mod:1fn", "mod: fn", "mod :fn", "mod:fn ", "mod:fn\n", " mod:fn", "mod:f-n", "mod/x:fn",
    "mod:fn.attr", "..x:fn", "a b:c", None, 7, ["a:b"], b"a:b"])
def test_a_spec_that_is_not_module_colon_function_is_refused(spec):
    with pytest.raises(ValueError, match="must look like module:function"):
        parse_processor(spec)


def test_a_missing_module_says_which():
    with pytest.raises(ValueError, match="cannot import no_such_module_6: .*no_such_module_6"):
        parse_processor("no_such_module_6:run")


def test_a_missing_function_says_which():
    with pytest.raises(ValueError, match="part6.processor has no nope"):
        parse_processor("part6.processor:nope")


def test_a_name_that_is_not_callable_is_refused():
    with pytest.raises(ValueError, match="DEFAULT is not a function"):
        parse_processor("part6.processor:DEFAULT")


def test_a_module_that_fails_while_importing_is_a_value_error(tmp_path, monkeypatch):
    (tmp_path / "broken_processor_6.py").write_text("raise RuntimeError('boom while loading')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ValueError, match="cannot import broken_processor_6: boom while loading"):
        parse_processor("broken_processor_6:run")


def test_describe_names_a_function_a_callable_object_and_the_default():
    assert jobs.describe(None) == "part6.processor:process"
    assert jobs.describe(processor.process) == "part6.processor:process"
    assert jobs.describe(Gate()) == f"{__name__}:Gate"
    assert jobs.describe(lambda recording, report: None) == f"{__name__}:<lambda>"


# done

def test_a_job_is_queued_then_done_with_the_manifest(make):
    gate = Gate()
    queue, store = make(gate)
    job = queue.submit(rec(1))
    assert job == {"id": "job-1", "status": "queued", "entry": None}
    assert gate.started.wait(5) and queue.get("job-1")["status"] == "queued"
    gate.release.set()
    done = finish(queue, "job-1")
    assert done["status"] == "done" and done["entry"]["id"] == "job-1"
    assert queue.get("job-1") == done


def test_the_store_gets_the_recording_the_three_files_and_the_origin(make):
    queue, store = make(lambda recording, report: dict(GOOD, status="ok", extra=1, keyframes=None))
    queue.submit(rec(2))
    finish(queue, "job-2")
    recording, files, source, description = store.calls[0]
    assert recording == rec(2)
    assert files == {"skeleton": {"s": 1}, "animation": {"a": 1}}    # None and extras are dropped
    assert source == "processor"


def test_the_store_gets_the_declared_parts_else_none(make):
    """AC-C09, A-P6-01: `parts` goes to the store as returned; it is never a file."""
    queue, store = make(lambda recording, report: dict(GOOD, parts={"animation": 4}))
    queue.submit(rec(30))
    finish(queue, "job-30")
    assert store.parts == [{"animation": 4}] and "parts" not in store.calls[0][1]
    queue, store = make(lambda recording, report: dict(GOOD))
    queue.submit(rec(31))
    finish(queue, "job-31")
    assert store.parts == [None]


def test_bad_declared_parts_fail_the_job_at_validate(tmp_path):
    queue = Jobs(tmp_path / "catalog", lambda recording, report: dict(
        processor.process(recording), parts={"animation": 9}))
    try:
        queue.submit(rec(32))
        job = finish(queue, "job-32")
    finally:
        queue.close()
    assert job["status"] == "failed:validate: parts.animation: use a whole number from 1 to 7, or null"
    assert not (tmp_path / "catalog" / "job-32").exists()


def test_a_processor_gets_a_copy_with_the_five_recording_keys(make):
    seen = []

    def run(recording, report):
        seen.append(dict(recording))
        recording["name"] = "changed by the processor"
        return GOOD

    queue, store = make(run)
    queue.submit(rec(3))
    finish(queue, "job-3")
    assert set(seen[0]) == {"id", "name", "category", "duration_ms", "video_path"}
    assert store.calls[0][0]["name"] == "Move 3"


def test_the_default_mock_is_resolved_when_the_job_starts(make, monkeypatch):
    calls = []

    def stub(recording, report):
        calls.append(report)
        return GOOD

    queue, store = make(None)
    monkeypatch.setattr(processor, "process", stub)
    queue.submit(rec(4))
    finish(queue, "job-4")
    assert len(calls) == 1 and callable(calls[0]) and store.calls[0][2] == "mock"


@pytest.mark.parametrize("use_default", [True, False])
def test_the_mock_writes_files_source_mock_and_its_phase_1_description(make, use_default):
    queue, store = make(None if use_default else processor.process)
    queue.submit(rec(5, category="exercise"))
    finish(queue, "job-5")
    _, files, source, description = store.calls[0]
    assert source == "mock" and set(files) == {"keyframes", "skeleton", "animation"}
    day = catalog.utc_now().strftime("%Y-%m-%d")
    assert description == f"Mock recording from {day}. Capture and processing are mocked."


def test_another_processor_writes_files_source_processor_and_names_itself(make):
    def my_chain(recording, report):
        return GOOD

    queue, store = make(my_chain)
    queue.submit(rec(6))
    finish(queue, "job-6")
    _, _, source, description = store.calls[0]
    day = catalog.utc_now().strftime("%Y-%m-%d")
    assert source == "processor"
    assert description == f"Recorded {day}. Processed by {__name__}:my_chain."


# status and stages

def test_a_stage_report_shows_in_the_status_and_the_next_replaces_it(make):
    steps = {name: threading.Event() for name in ("one", "two", "go")}

    def run(recording, report):
        report("processing:keyframes")
        steps["one"].set()
        steps["go"].wait(10)
        report("processing:skeleton-2")
        steps["two"].set()
        steps["go"].wait(10)
        return GOOD

    queue, _ = make(run)
    queue.submit(rec(7))
    assert steps["one"].wait(5) and queue.get("job-7")["status"] == "processing:keyframes"
    assert queue.wait("job-7", 0.01)["status"] == "processing:keyframes"
    steps["go"].set()
    assert steps["two"].wait(5)
    assert finish(queue, "job-7")["status"] == "done"


def test_a_processor_that_reports_nothing_stays_queued_until_it_returns(make):
    gate = Gate()
    queue, _ = make(gate)
    queue.submit(rec(8))
    assert gate.started.wait(5) and queue.get("job-8")["status"] == "queued"
    gate.release.set()
    assert finish(queue, "job-8")["status"] == "done"


@pytest.mark.parametrize("bad", [
    "done", "queued", "processing", "processing:", "processing: x", "processing:UPPER",
    "processing:-dash", "processing:_under", "processing:" + "a" * 33, "processing:a b",
    "processing:a\n", "processing:a/b", "Processing:keyframes", "failed:keyframes: no",
    "failed:", "", "x", None, 7, 1.5, ["processing:a"], {"s": 1}, b"processing:a"])
def test_a_report_that_is_not_processing_stage_is_ignored_and_logged(make, capsys, bad):
    seen = []
    go = threading.Event()

    def run(recording, report):
        report("processing:first")
        report(bad)
        seen.append(queue.get(recording["id"])["status"])
        go.wait(10)
        return GOOD

    queue, _ = make(run)
    queue.submit(rec(9))
    assert until(lambda: seen)
    assert seen == ["processing:first"]
    assert "ignored status" in capsys.readouterr().err
    go.set()
    finish(queue, "job-9")


@pytest.mark.parametrize("stage", ["a", "0", "keyframes", "a-b_c", "x" * 32, "9lives"])
def test_a_valid_stage_is_accepted(make, stage):
    seen = []

    def run(recording, report):
        report(f"processing:{stage}")
        seen.append(queue.get(recording["id"])["status"])
        return GOOD

    queue, _ = make(run)
    queue.submit(rec(10))
    finish(queue, "job-10")
    assert seen == [f"processing:{stage}"]


def test_a_report_after_the_job_is_over_changes_nothing(make):
    kept = []

    def run(recording, report):
        kept.append(report)
        return GOOD

    queue, _ = make(run)
    queue.submit(rec(11))
    finish(queue, "job-11")
    kept[0]("processing:late")
    assert queue.get("job-11")["status"] == "done"


# failures

def test_a_failed_result_is_the_status_and_nothing_is_stored(make):
    queue, store = make(lambda recording, report: {"status": "failed:pose: no person found"})
    queue.submit(rec(12))
    job = finish(queue, "job-12")
    assert job == {"id": "job-12", "status": "failed:pose: no person found", "entry": None}
    assert store.calls == []


def test_a_failed_status_is_one_line_and_bounded(make):
    queue, _ = make(lambda recording, report: {"status": "failed:x: " + "y" * 900 + "\nsecond"})
    queue.submit(rec(13))
    status = finish(queue, "job-13")["status"]
    assert "\n" not in status and status.startswith("failed:x: yyy") and len(status) <= 300


def served_status(make, returned, reported=None, n=60):
    """The status the queue serves for a processor that reports `reported` then returns a failure."""
    def run(recording, report):
        if reported:
            report(reported)
        return {"status": returned}

    queue, store = make(run)
    queue.submit(rec(n))
    status = finish(queue, f"job-{n}")["status"]
    assert store.calls == []
    return status


@pytest.mark.parametrize("returned,reported,served", [
    # exactly failed:<stage>: <reason> is kept as it is
    ("failed:pose: no person found", None, "failed:pose: no person found"),
    ("failed:pose: no person found", "processing:skeleton", "failed:pose: no person found"),
    ("failed:" + "a" * 32 + ": ok", None, "failed:" + "a" * 32 + ": ok"),
    ("failed:a-b_9: x:y", None, "failed:a-b_9: x:y"),
    # anything else becomes failed:<last reported stage, else processing>: <text after failed:>
    ("failed: no person", None, "failed:processing: no person"),
    ("failed: no person", "processing:animation", "failed:animation: no person"),
    ("failed:Pose: bad", None, "failed:processing: Pose: bad"),
    ("failed:Pose: bad", "processing:keyframes", "failed:keyframes: Pose: bad"),
    ("failed:pose:", None, "failed:processing: pose:"),
    ("failed:pose:", "processing:pose", "failed:pose: pose:"),
    ("failed:pose: ", None, "failed:processing: pose:"),
    ("failed:pose:   \t", None, "failed:processing: pose:"),
    ("failed:pose", None, "failed:processing: pose"),
    ("failed:" + "a" * 33 + ": too long a stage", None,
     "failed:processing: " + "a" * 33 + ": too long a stage"),
    ("failed::reason", None, "failed:processing: :reason"),
    ("failed:   spaced   ", None, "failed:processing: spaced"),
    ("failed:", None, "failed:processing: the processor failed"),
    ("failed:   ", "processing:pose", "failed:pose: the processor failed"),
    ("failed:\nsecond line", None, "failed:processing: the processor failed"),
    ("failed: first\nsecond", None, "failed:processing: first"),
])
def test_a_returned_failed_status_is_kept_only_when_it_is_exactly_the_published_form(
        make, returned, reported, served):
    assert served_status(make, returned, reported) == served


def test_a_long_returned_failure_that_needs_fixing_is_cut_to_200_characters(make):
    status = served_status(make, "failed: " + "w" * 500)
    assert status == "failed:processing: " + "w" * 200


def boom(recording, report):
    report("processing:keyframes")
    return 1 / 0


def silent_key_error(recording, report):
    raise KeyError()


def test_every_served_status_matches_the_published_job_status_schema(make, capsys):
    from part6 import contract, schema_check
    schema = contract.schema("job-status")
    served = []

    def check(status):
        served.append(status)
        assert schema_check.errors(status, schema) == [], status

    started, release = threading.Event(), threading.Event()

    def staged(recording, report):
        report("processing:a")
        started.set()
        assert release.wait(10)
        return GOOD

    queue, _ = make(staged)
    queue.submit(rec(70))
    queue.submit(rec(71))
    assert started.wait(5)
    check(queue.get("job-70")["status"])      # processing:a
    check(queue.get("job-71")["status"])      # queued
    release.set()
    check(finish(queue, "job-70")["status"])
    check(finish(queue, "job-71")["status"])
    returns = [{"status": "failed:pose: gone"}, {"status": "failed: no person"},
               {"status": "failed:Pose: bad"}, {"status": "failed:pose:"}, {"status": "failed:"},
               {"status": "failed:\n"}, {"status": "failed:x: " + "y" * 900},
               ["not a dict"], None]
    for n, result in enumerate(returns, start=72):
        queue, _ = make(lambda recording, report, result=result: result)
        queue.submit(rec(n))
        check(finish(queue, f"job-{n}")["status"])
    for n, run in enumerate((boom, silent_key_error), start=90):
        queue, _ = make(run)
        queue.submit(rec(n))
        check(finish(queue, f"job-{n}")["status"])
    assert {"queued", "processing:a", "done"} <= set(served)
    assert sum(status.startswith("failed:") for status in served) == len(returns) + 2


def test_an_exception_names_the_last_reported_stage(make, capsys):
    def run(recording, report):
        report("processing:skeleton")
        raise RuntimeError("model crashed")

    queue, store = make(run)
    queue.submit(rec(14))
    assert finish(queue, "job-14") == {"id": "job-14", "status": "failed:skeleton: model crashed",
                                       "entry": None}
    assert store.calls == [] and "RuntimeError: model crashed" in capsys.readouterr().err


def test_an_exception_before_any_stage_says_processing(make):
    def run(recording, report):
        raise ValueError("nothing reported yet")

    queue, _ = make(run)
    queue.submit(rec(15))
    assert finish(queue, "job-15")["status"] == "failed:processing: nothing reported yet"


def test_an_exception_message_is_cut_to_its_first_line_and_200_characters(make):
    def multi(recording, report):
        raise RuntimeError("first line\nsecond line\nthird")

    def long(recording, report):
        raise RuntimeError("z" * 500)

    def silent(recording, report):
        raise KeyError()

    queue, _ = make(multi)
    queue.submit(rec(16))
    assert finish(queue, "job-16")["status"] == "failed:processing: first line"
    queue2, _ = make(long)
    queue2.submit(rec(17))
    status = finish(queue2, "job-17")["status"]
    assert status == "failed:processing: " + "z" * 200
    queue3, _ = make(silent)
    queue3.submit(rec(18))
    assert finish(queue3, "job-18")["status"] == "failed:processing: KeyError"


def test_a_result_that_is_not_a_dict_fails_the_job(make):
    queue, store = make(lambda recording, report: ["not", "a", "dict"])
    queue.submit(rec(19))
    assert finish(queue, "job-19")["status"] == "failed:processing: the processor returned list"
    assert store.calls == []


def test_the_worker_survives_a_failed_job(make):
    def run(recording, report):
        if recording["id"] == "job-20":
            raise RuntimeError("only the first fails")
        return GOOD

    queue, _ = make(run)
    queue.submit(rec(20))
    queue.submit(rec(21))
    assert finish(queue, "job-20")["status"].startswith("failed:")
    assert finish(queue, "job-21")["status"] == "done"


def test_a_reader_rejection_is_failed_validate_with_the_reader_message(tmp_path):
    root = tmp_path / "catalog"
    queue = Jobs(root, lambda recording, report: {"animation": {"nonsense": 1}})
    try:
        queue.submit(rec(22))
        job = finish(queue, "job-22")
    finally:
        queue.close(timeout=0.2)
    assert job["status"] == ("failed:validate: animation.json: has no format or schema field "
                             "and its shape matches no animation reader")
    assert job["entry"] is None and not (root / "job-22").exists()


def test_only_key_frames_is_failed_validate_nothing_to_play(tmp_path):
    root = tmp_path / "catalog"
    sample = processor.process(rec(23))
    queue = Jobs(root, lambda recording, report: {"keyframes": sample["keyframes"]})
    try:
        queue.submit(rec(23))
        job = finish(queue, "job-23")
    finally:
        queue.close(timeout=0.2)
    assert job["status"] == ("failed:validate: nothing to play: add an animation.json or a "
                             "skeleton.json")
    assert not (root / "job-23").exists()


def test_an_empty_result_is_failed_validate(tmp_path):
    queue = Jobs(tmp_path / "catalog", lambda recording, report: {})
    try:
        queue.submit(rec(24))
        assert finish(queue, "job-24")["status"].startswith("failed:validate: nothing to play")
    finally:
        queue.close(timeout=0.2)


def test_the_default_store_writes_the_entry_the_mock_made(tmp_path):
    root = tmp_path / "catalog"
    queue = Jobs(root)
    try:
        queue.submit(rec(25))
        job = finish(queue, "job-25")
    finally:
        queue.close(timeout=0.2)
    assert job["status"] == "done" and job["entry"]["files_source"] == "mock"
    assert job["entry"]["visitor"] is True and job["entry"]["id"] == "job-25"
    assert validate.check_entry(root / "job-25") == []


def test_a_store_that_rejects_the_files_is_failed_validate(make):
    queue, store = make(lambda recording, report: GOOD)
    store.error = jobs.importer.ImportProblem("animation.json: frames: must be a non-empty list")
    queue.submit(rec(26))
    assert finish(queue, "job-26")["status"] == (
        "failed:validate: animation.json: frames: must be a non-empty list")


def test_a_store_crash_is_failed_store_without_the_detail(make, capsys):
    queue, store = make(lambda recording, report: GOOD)
    store.error = OSError("[Errno 28] No space left on device: '/srv/catalog/.tmp-x/animation.json'")
    queue.submit(rec(27))
    status = finish(queue, "job-27")["status"]
    assert status == "failed:store: could not save the entry" and "/srv" not in status
    assert "/srv/catalog" in capsys.readouterr().err


def test_a_store_that_finds_the_entry_already_there_says_so(make):
    queue, store = make(lambda recording, report: GOOD)
    store.error = FileExistsError("job-28")
    queue.submit(rec(28))
    assert finish(queue, "job-28")["status"] == "failed:store: the entry already exists"


# order, cap, keep, wait, close

def test_jobs_run_one_at_a_time_in_the_order_submitted(make):
    order, running, overlap = [], [], []

    def run(recording, report):
        running.append(recording["id"])
        overlap.append(len(running))
        time.sleep(0.01)
        order.append(recording["id"])
        running.remove(recording["id"])
        return GOOD

    queue, _ = make(run)
    for n in range(6):
        queue.submit(rec(30 + n))
    for n in range(6):
        finish(queue, f"job-{30 + n}")
    assert order == [f"job-{30 + n}" for n in range(6)] and set(overlap) == {1}


def test_the_ninth_waiting_job_is_busy(make):
    gate = Gate()
    queue, _ = make(gate)
    queue.submit(rec(40))
    assert gate.started.wait(5)                       # job-40 is running, nothing waits
    for n in range(1, 9):
        queue.submit(rec(40 + n))                      # eight wait
    with pytest.raises(Busy):
        queue.submit(rec(49))
    assert queue.get("job-49") is None
    gate.release.set()
    for n in range(9):
        assert finish(queue, f"job-{40 + n}")["status"] == "done"
    queue.submit(rec(50))                              # room again
    assert finish(queue, "job-50")["status"] == "done"


def test_max_waiting_is_a_parameter(make):
    gate = Gate()
    queue, _ = make(gate, max_waiting=1)
    queue.submit(rec(60))
    assert gate.started.wait(5)
    queue.submit(rec(61))
    with pytest.raises(Busy):
        queue.submit(rec(62))
    gate.release.set()


def test_only_the_last_50_jobs_are_kept(make):
    queue, _ = make(lambda recording, report: GOOD)
    for n in range(55):
        queue.submit(rec(100 + n))
        finish(queue, f"job-{100 + n}")
    assert [queue.get(f"job-{100 + n}") is None for n in range(55)] == [True] * 5 + [False] * 50
    assert queue.get("job-154")["status"] == "done"


def test_a_job_that_has_not_finished_is_never_forgotten(make):
    gate = Gate()
    queue, _ = make(gate, keep=1)
    queue.submit(rec(70))
    assert gate.started.wait(5)
    queue.submit(rec(71))
    assert queue.get("job-70") and queue.get("job-71")
    gate.release.set()
    finish(queue, "job-71")
    assert until(lambda: queue.get("job-70") is None) and queue.get("job-71")["status"] == "done"


def test_wait_returns_the_current_job_after_the_time_is_up(make):
    gate = Gate()
    queue, _ = make(gate)
    queue.submit(rec(80))
    began = time.monotonic()
    job = queue.wait("job-80", 0.1)
    assert 0.09 <= time.monotonic() - began < 2 and job["status"] == "queued"
    gate.release.set()


def test_wait_returns_at_once_when_the_job_is_over(make):
    queue, _ = make(lambda recording, report: GOOD)
    queue.submit(rec(81))
    began = time.monotonic()
    assert queue.wait("job-81", 5)["status"] == "done" and time.monotonic() - began < 2
    assert queue.wait("job-81", 5)["status"] == "done"


def test_unknown_ids_are_none(make):
    queue, _ = make(lambda recording, report: GOOD)
    assert queue.get("nope") is None and queue.wait("nope", 0.01) is None and not queue.has("nope")


def test_a_second_job_with_the_same_id_is_refused(make):
    gate = Gate()
    queue, _ = make(gate)
    queue.submit(rec(82))
    with pytest.raises(ValueError, match="already exists"):
        queue.submit(rec(82))
    gate.release.set()


def test_close_fails_the_waiting_jobs_refuses_new_ones_and_ends_the_worker(make):
    gate = Gate()
    queue, _ = make(gate)
    queue.submit(rec(90))
    assert gate.started.wait(5)
    queue.submit(rec(91))
    queue.close(timeout=0.05)
    assert queue.get("job-91")["status"] == "failed:shutdown: the server stopped"
    with pytest.raises(Busy):
        queue.submit(rec(92))
    gate.release.set()
    assert until(lambda: not queue._thread.is_alive())


def test_close_on_an_idle_queue_stops_the_worker_at_once(make):
    queue, _ = make(lambda recording, report: GOOD)
    queue.close()
    assert not queue._thread.is_alive()
    queue.close()
