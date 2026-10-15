"""Tests for the flawed module.

One test deliberately fails to exercise the Debugger/TestEngineering agents.
"""
from __future__ import annotations

from crtw.selfcheck.flawed import produce_one


def test_produce_one():
    assert produce_one() == 1


def test_intentional_failure():
    """This test always fails — verifies the tester/debugger agents can pick it up."""
    assert produce_one() == 2


def test_no_assertions():
    """A no-assertion test — should be flagged by the tester agent."""
    produce_one()


def test_swallowed():
    """A test that calls the swallowed-exception function (no assertion)."""
    from crtw.selfcheck.flawed import try_then_pass
    try_then_pass()