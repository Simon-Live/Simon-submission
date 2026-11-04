"""TICKET-380: a cut SAM 3.1 stream is tried again, a bounded number of times, and never read as a full answer."""

import http.client
import json
import unittest
from unittest import mock

from keyframe_finder import meta_client


def _sse(*events):
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode("utf-8")


DONE = {"type": "response.completed", "response": {"usage": {"video_frames_processed": 60}}}


class _Response:
    """A streamed answer: `body` in chunks, then `then` (an exception to raise, or None for a clean end)."""

    def __init__(self, body, then=None):
        self.chunks = [body[i : i + 64] for i in range(0, len(body), 64)]
        self.then = then

    def read(self, _size=-1):
        if _size < 0:   # the whole body, as urlopen's read() gives it
            body, self.chunks = b"".join(self.chunks), []
            return body
        if self.chunks:
            return self.chunks.pop(0)
        if self.then is not None:
            raise self.then
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TrackPeopleRetry(unittest.TestCase):
    def setUp(self):
        self.recorded = []
        patches = [
            mock.patch.object(meta_client, "require_budget", lambda *a, **k: None),
            mock.patch.object(meta_client, "record", lambda usd, note, model=None: self.recorded.append(note) or []),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.waits = []

    def run_with(self, responses, tries=2, deadline=None, clock=None):
        it = iter(responses)
        with mock.patch.object(meta_client, "_stream", lambda body, timeout: next(it)):
            return meta_client.track_people("file-1", 60, tries=tries, wait_s=1.0, sleep=self.waits.append,
                                            deadline=deadline, **({"clock": clock} if clock else {}))

    def test_a_cut_stream_is_tried_again_and_the_second_answer_is_used(self):
        cut = _Response(_sse({"type": "response.output_text.delta", "delta": ""}), http.client.IncompleteRead(b""))
        whole = _Response(_sse(DONE))
        tracks, _ = self.run_with([cut, whole])
        self.assertEqual(tracks, meta_client.BoxParser().tracks)
        self.assertEqual(self.waits, [1.0])
        # each try is recorded at its estimate when it starts (TICKET-380 review), so a killed try still counts
        self.assertEqual(len(self.recorded), 2)
        self.assertIn("try 1 (estimate at start)", self.recorded[0])
        self.assertIn("try 2 (estimate at start)", self.recorded[1])

    def test_a_stream_that_closes_without_completing_is_a_cut_not_a_full_answer(self):
        early = _Response(_sse({"type": "response.output_text.delta", "delta": ""}))   # ends cleanly, no completed
        with self.assertRaises(meta_client.StreamCut):
            self.run_with([early, _Response(b"")])
        self.assertEqual(len(self.recorded), 2, "both tries are recorded")

    def test_tries_are_bounded(self):
        cuts = [_Response(b"", http.client.IncompleteRead(b"")) for _ in range(5)]
        with self.assertRaises(meta_client.StreamCut):
            self.run_with(cuts, tries=3)
        self.assertEqual(self.waits, [1.0, 2.0])
        self.assertEqual(len(self.recorded), 3)

    def test_a_model_error_is_not_retried(self):
        failed = _Response(_sse({"type": "response.failed", "error": {"message": "bad video"}}))
        with self.assertRaises(RuntimeError) as caught:
            self.run_with([failed, _Response(_sse(DONE))])
        self.assertNotIsInstance(caught.exception, meta_client.StreamCut)
        self.assertEqual(self.waits, [])



class ReviewFixes(TrackPeopleRetry):
    """TICKET-380 review (moalborati/simon#61 6621762147)."""

    def test_a_stream_closed_mid_event_is_a_cut_and_is_tried_again(self):
        broken = _Response(b'data: {"type": "response.output_text.delta", "del')   # the close leaves half an event
        tracks, _ = self.run_with([broken, _Response(_sse(DONE))])
        self.assertEqual(self.waits, [1.0])

    def test_no_second_try_when_the_deadline_leaves_no_time_for_it(self):
        now = [1000.0]
        def clock():
            now[0] += 40.0   # each look at the clock is 40 s later: the cut try took 40 s
            return now[0]
        cut = _Response(b"", http.client.IncompleteRead(b""))
        with self.assertRaises(meta_client.StreamCut):
            self.run_with([cut, _Response(_sse(DONE))], deadline=1100.0, clock=clock)
        self.assertEqual(self.waits, [], "negative: the second paid try never starts")
        self.assertEqual(len(self.recorded), 1)

    def test_a_far_deadline_still_allows_the_second_try(self):
        cut = _Response(b"", http.client.IncompleteRead(b""))
        self.run_with([cut, _Response(_sse(DONE))], deadline=10 ** 12)
        self.assertEqual(self.waits, [1.0])


class LedgerLock(unittest.TestCase):
    def test_overlapping_writers_keep_every_record(self):
        import tempfile
        import threading
        from keyframe_finder import spend
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(spend, "LEDGER", __import__("pathlib").Path(tmp) / "spend.json"):
            def write(n):
                for i in range(25):
                    spend.record(0.01, f"writer {n} call {i}")
            threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            ledger = spend._load()
            self.assertEqual(len(ledger["entries"]), 100)
            self.assertAlmostEqual(ledger["usd"], 1.0, places=6)


class UploadRetry(unittest.TestCase):
    def test_a_cut_upload_is_tried_again(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise http.client.RemoteDisconnected("cut")
            return _Response(b'{"id": "file-9"}')

        waits = []
        with mock.patch.object(meta_client, "urlopen", fake_urlopen), \
                mock.patch.object(meta_client, "_multipart", lambda path: ("b", b"x")), \
                mock.patch.object(meta_client, "api_key", lambda: "k"):
            self.assertEqual(meta_client.upload_video("v.mp4", tries=2, wait_s=1.0, sleep=waits.append), "file-9")
        self.assertEqual(len(calls), 2)
        self.assertEqual(waits, [1.0])

    def test_an_upload_cut_every_time_gives_up(self):
        def cut(request, timeout):
            raise http.client.RemoteDisconnected("cut")

        with mock.patch.object(meta_client, "urlopen", cut), \
                mock.patch.object(meta_client, "_multipart", lambda path: ("b", b"x")), \
                mock.patch.object(meta_client, "api_key", lambda: "k"):
            with self.assertRaises(meta_client.StreamCut):
                meta_client.upload_video("v.mp4", tries=2, wait_s=0.0, sleep=lambda s: None)



class DeleteFileSays(unittest.TestCase):
    """TICKET-388: a delete says whether it worked, with the file id, and never raises."""

    def run_delete(self, request):
        import io
        import contextlib
        out = io.StringIO()
        with mock.patch.object(meta_client, "_request", request), contextlib.redirect_stdout(out):
            self.assertIsNone(meta_client.delete_file("file-7"))
        return out.getvalue()

    def test_a_delete_that_works_says_ok_with_the_id(self):
        class Ok:
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
        self.assertIn("delete_file ok file_id=file-7", self.run_delete(lambda *a, **k: Ok()))

    def test_a_refused_delete_says_failed_with_the_id_and_the_reason(self):
        def refused(*a, **k):
            raise RuntimeError("Meta API 403 on /files/file-7: no")
        said = self.run_delete(refused)
        self.assertIn("delete_file failed file_id=file-7: Meta API 403", said)

    def test_a_dropped_connection_says_failed(self):
        def dropped(*a, **k):
            raise ConnectionResetError("reset")
        self.assertIn("delete_file failed file_id=file-7: ConnectionResetError", self.run_delete(dropped))


class StopHandler(unittest.TestCase):
    """TICKET-388: SIGTERM ends a run like an exception, so `finally` (the delete) still runs."""

    def test_sigterm_runs_the_finally_and_exits_143(self):
        import os
        import subprocess
        import sys
        import tempfile
        import time
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "deleted"
            code = (
                "import sys, time\n"
                f"sys.path.insert(0, {str(root)!r})\n"
                "import keyframe_finder.from_video as fv\n"
                "fv.install_stop_handler()\n"
                "try:\n"
                "    print('ready', flush=True)\n"
                "    time.sleep(30)\n"
                "finally:\n"
                f"    open({str(marker)!r}, 'w').write('yes')\n"
            )
            proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
            self.assertEqual(proc.stdout.readline().strip(), "ready")
            proc.terminate()
            self.assertEqual(proc.wait(timeout=20), 143)
            self.assertTrue(marker.exists(), "the finally ran")


if __name__ == "__main__":
    unittest.main()
