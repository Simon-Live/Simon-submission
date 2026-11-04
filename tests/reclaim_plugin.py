"""Fixtures that leave no process behind a test (docs/specs/test-process-reclaim.md AC-2, TICKET-379).

`tests/conftest.py` imports both, so they are autouse for the whole suite; a test of the plugin loads this module with
`-p reclaim_plugin`. A detached daemon (`setsid nohup`, as `staging/converter.sh` starts the model converter) outlives
its test and, with no owner, its pytest session; this stops whatever still names the test's temp dir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

import process_reclaim


@pytest.fixture(autouse=True)
def _reap_test_processes(tmp_path: Path) -> Iterator[None]:
    """After every test, pass or fail, stop any process whose command line names this test's tmp_path."""
    yield
    process_reclaim.reap([tmp_path])


@pytest.fixture(autouse=True, scope="session")
def _reap_session_processes(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """At the end of the session, stop any process naming a path under pytest's base temp dir (module-scoped state)."""
    yield
    process_reclaim.reap([tmp_path_factory.getbasetemp()])
