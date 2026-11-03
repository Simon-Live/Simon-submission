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

    def read(self, _size):
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

    def run_with(self, responses, tries=2):
        it = iter(responses)
        with mock.patch.object(meta_client, "_stream", lambda body, timeout: next(it)):
            return meta_client.track_people("file-1", 60, tries=tries, wait_s=1.0, sleep=self.waits.append)

    def test_a_cut_stream_is_tried_again_and_the_second_answer_is_used(self):
        cut = _Response(_sse({"type": "response.output_text.delta", "delta": ""}), http.client.IncompleteRead(b""))
        whole = _Response(_sse(DONE))
        tracks, _ = self.run_with([cut, whole])
        self.assertEqual(tracks, meta_client.BoxParser().tracks)
        self.assertEqual(self.waits, [1.0])
        self.assertEqual(len(self.recorded), 2)
        self.assertIn("cut on try 1", self.recorded[0])
        self.assertIn("60 frames", self.recorded[1])

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


if __name__ == "__main__":
    unittest.main()
