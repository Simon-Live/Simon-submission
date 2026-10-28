"""Test support for the run app tests (not a test module): the real HTTP server on a socket, the pure logic's call
helpers and the clips built for the views. The test modules import from here and never from each other, as the
doctor tests do from `doctorkit`."""

import contextlib
import copy
import http.client
import json
import threading

import numpy as np
import pytest

from conftest import ROOT
from part3 import runapi, server

BASE = "/simon-part-3/"
REPLY_KEYS = ["ok", "source", "flip", "options", "metrics", "input_frames", "bones", "angles", "skeleton_text",
              "output_text", "output_name", "run_ms"]
TAKE_1 = ROOT / "fixtures" / "input" / "synthetic-4take" / "take-1" / "pose3d.json"
UPPER_ARM_M, FOREARM_M = 0.3162, 0.2482


# ---- the server on a real socket ---------------------------------------------------------------

class Reply:
    def __init__(self, response, body):
        self.status, self.body = response.status, body
        self.headers = {name.lower(): value for name, value in response.getheaders()}

    def json(self):
        return json.loads(self.body)

    def error_code(self):
        return self.json()["error"]["code"]


class Client:
    def __init__(self, port, base):
        self.port, self.base = port, base

    def connect(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)

    def raw(self, method, path, body=None, headers=None):
        conn = self.connect()
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return Reply(response, response.read())
        finally:
            conn.close()

    def get(self, rel, **kwargs):
        return self.raw("GET", self.base + rel, **kwargs)

    def post(self, rel, body=b"", headers=None):
        return self.raw("POST", self.base + rel, body=body, headers=headers)

    def run(self, query, body=b""):
        return self.post("api/run?" + query, body)


@contextlib.contextmanager
def serving(base=BASE, web_dir=None):
    app = server.AppServer(("127.0.0.1", 0), base, web_dir)
    thread = threading.Thread(target=app.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield Client(app.server_address[1], app.base)
    finally:
        app.shutdown()
        app.server_close()
        thread.join(5)


def post_head(client, *headers, query=""):
    """A POST to api/run whose request line and chosen headers are sent; the caller sends any body."""
    conn = client.connect()
    conn.putrequest("POST", BASE + "api/run" + query)
    for header in headers:
        conn.putheader(*header)
    conn.endheaders()
    return conn


def answer(conn):
    response = conn.getresponse()
    return response.status, json.loads(response.read())["error"]["code"], response


# ---- the pure logic: one run, the error body ---------------------------------------------------

def file_of(sample_id):
    return ROOT / "fixtures" / "input" / next(rel for sid, rel, _ in runapi.SAMPLES if sid == sample_id)


def run_sample(sample_id, flip="auto"):
    return runapi.handle(sample_id, flip, None, b"")


def upload(doc, flip="auto", name="clip.json"):
    return runapi.handle(None, flip, name, json.dumps(doc).encode())


def code_of(result):
    status, body = result
    assert body["ok"] is False and list(body) == ["ok", "error"]
    assert list(body["error"]) == ["code", "field", "message"]
    return status, body["error"]


@pytest.fixture
def clip(real_doc):
    """A private 40-frame copy of the real clip with a new person id."""
    doc = copy.deepcopy(real_doc)
    doc["frames"] = doc["frames"][:40]
    for frame in doc["frames"]:
        for person in frame["people"]:
            person["id"] = 7
    return doc


def options_for(query):
    options, failure = runapi.parse_options(query)
    assert failure is None
    return options


# ---- clips for the views -----------------------------------------------------------------------

def take1_with_arms(directions):
    """take-1's pose3d.json with the elbows and wrists put along `directions(side, u)` at the arm lengths.

    `u` is the share of the clip (0 to 1); a unit vector in the input frame sets the whole arm, None keeps
    that side's input arm.
    """
    source = json.loads(TAKE_1.read_text())
    frames = [f for f in source["frames"] if f["people"]]
    clip = {"frames": []}
    for i, frame in enumerate(frames):
        joints = copy.deepcopy(frame["people"][0]["joints"])
        for side in ("left", "right"):
            direction = directions(side, i / (len(frames) - 1))
            if direction is None:
                continue
            shoulder = joints[f"{side}_shoulder"]
            for name, length in ((f"{side}_elbow", UPPER_ARM_M), (f"{side}_wrist", UPPER_ARM_M + FOREARM_M)):
                joints[name] = {**{a: shoulder[a] + direction[k] * length for k, a in enumerate("xyz")},
                                "conf": 0.9}
        clip["frames"].append({"frame": frame["frame"], "t_ms": frame["t_ms"],
                               "people": [{"id": 0, "joints": joints}]})
    return clip


def across_the_body(side, u):
    """The left arm points across the chest, slightly down for the first half of the clip and slightly up after."""
    if side == "right":
        return None
    direction = np.array([-1.0, 0.3 if u >= 0.5 else -0.3, 0.0])
    return tuple(direction / np.linalg.norm(direction))
