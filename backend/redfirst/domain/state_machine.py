"""Investigation lifecycle: explicit, validated state transitions."""

from redfirst.domain.enums import InvestigationState as S

TERMINAL_STATES = frozenset({S.COMPLETED, S.FAILED, S.CANCELLED})

_PIPELINE = [
    S.CREATED,
    S.ANALYZING_REPORT,
    S.ANALYZING_REPOSITORY,
    S.GENERATING_TEST,
    S.VALIDATING_TEST,
    S.EXECUTING_TEST,
    S.VERIFYING_RESULT,
    S.COMPLETED,
]

ALLOWED_TRANSITIONS: dict[S, frozenset[S]] = {
    state: frozenset({nxt, S.FAILED, S.CANCELLED})
    for state, nxt in zip(_PIPELINE, _PIPELINE[1:], strict=False)
}
# Bounded regeneration loops (the attempt limit is enforced by the orchestrator).
ALLOWED_TRANSITIONS[S.VALIDATING_TEST] |= {S.GENERATING_TEST}
ALLOWED_TRANSITIONS[S.VERIFYING_RESULT] |= {S.GENERATING_TEST}
# A run that exhausts its attempts still completes, with an INCONCLUSIVE outcome.
ALLOWED_TRANSITIONS[S.GENERATING_TEST] |= {S.COMPLETED}
for _t in TERMINAL_STATES:
    ALLOWED_TRANSITIONS[_t] = frozenset()


class InvalidTransition(ValueError):
    pass


def is_terminal(state: S) -> bool:
    return state in TERMINAL_STATES


def ensure_transition(current: S, target: S) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(f"{current.value} -> {target.value} is not allowed")
