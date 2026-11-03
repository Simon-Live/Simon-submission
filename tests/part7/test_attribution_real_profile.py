"""Attribution against the REAL profile module and the REAL identity store (no mocks): TICKET-231 + TICKET-232."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from part7 import attribution, identity, profile

ENTRY, JOB = "lateral-raise", "job-real-1"


@pytest.fixture()
def store(tmp_path: Path) -> identity.IdentityStore:
    return identity.IdentityStore(tmp_path, b"p" * 32)


def user(store: identity.IdentityStore, email: str) -> str:
    return store._user_for(email, store.clock())


def test_the_real_profile_names_an_entry_and_a_take_only_as_the_owner_allows(store: identity.IdentityStore) -> None:
    trainer, follower = user(store, "trainer@example.com"), user(store, "follower@example.com")
    store.attach_entry(ENTRY, trainer)
    store.attach(JOB, follower, "follow", ENTRY, None, "claim")
    profile.update(store, trainer, {"public_name": "Tess Trainer", "show_name": True, "credit_me_as_trainer": True})
    profile.update(store, follower, {"public_name": "Fay Follower", "show_name": True})

    entry = attribution.author_line(store, attribution.entry_subject(store, ENTRY))
    take = attribution.author_line(store, attribution.take_subject(store, JOB, ENTRY))
    assert entry["author"]["name"] == "Tess Trainer"
    assert take["author"]["name"] == "Fay Follower" and take["trainer_credit"]["name"] == "Tess Trainer"

    profile.update(store, follower, {"show_name": False})  # negative: name hidden by the owner
    hidden = attribution.author_line(store, attribution.take_subject(store, JOB, ENTRY))
    assert hidden["author"]["name"] is None and hidden["trainer_credit"]["name"] == "Tess Trainer"

    profile.update(store, trainer, {"credit_me_as_trainer": False})  # trainer credit governed by its own switch
    assert attribution.author_line(store, attribution.entry_subject(store, ENTRY))["author"]["name"] is None
    assert attribution.author_line(store, attribution.take_subject(store, JOB, ENTRY))["trainer_credit"] is None

    profile.update(store, trainer, {"credit_me_as_trainer": True, "show_name": False})
    assert attribution.author_line(store, attribution.entry_subject(store, ENTRY))["author"]["name"] is None  # no public name shown

    seen = json.dumps([entry, take, hidden]).lower()
    assert "example.com" not in seen and "@" not in seen  # never an email
