import pytest

from redfirst.domain.enums import InvestigationState as S
from redfirst.domain.state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidTransition,
    ensure_transition,
    is_terminal,
)


def test_happy_path_is_allowed():
    path = [S.CREATED, S.ANALYZING_REPORT, S.ANALYZING_REPOSITORY, S.GENERATING_TEST,
            S.VALIDATING_TEST, S.EXECUTING_TEST, S.VERIFYING_RESULT, S.COMPLETED]
    for a, b in zip(path, path[1:], strict=False):
        ensure_transition(a, b)


@pytest.mark.parametrize("state", [S.COMPLETED, S.FAILED, S.CANCELLED])
def test_terminal_states_have_no_exits(state):
    assert is_terminal(state)
    assert ALLOWED_TRANSITIONS[state] == frozenset()
    with pytest.raises(InvalidTransition):
        ensure_transition(state, S.CREATED)


def test_cannot_skip_stages():
    with pytest.raises(InvalidTransition):
        ensure_transition(S.CREATED, S.EXECUTING_TEST)


def test_regeneration_loops_allowed_only_from_validation_and_verification():
    ensure_transition(S.VALIDATING_TEST, S.GENERATING_TEST)
    ensure_transition(S.VERIFYING_RESULT, S.GENERATING_TEST)
    with pytest.raises(InvalidTransition):
        ensure_transition(S.EXECUTING_TEST, S.GENERATING_TEST)


def test_any_active_state_can_fail_or_cancel():
    for s in S:
        if not is_terminal(s):
            ensure_transition(s, S.FAILED)
            ensure_transition(s, S.CANCELLED)
