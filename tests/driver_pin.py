"""Test helper: pin the roster driver kind for one test case. The tests that measure the *anchor* driver (roster_driven demotions, anchor counts, inert
walking tasks) must hold whatever ``EDEN_ROSTER_DRIVER`` the whole suite runs under (D-008: ``anchor`` default, ``agent`` for the R3-INT runs)."""
import os
from unittest import mock


def pin_anchor(case, kind: str = "anchor"):
    patcher = mock.patch.dict(os.environ, {"EDEN_ROSTER_DRIVER": kind})
    patcher.start()
    case.addCleanup(patcher.stop)
