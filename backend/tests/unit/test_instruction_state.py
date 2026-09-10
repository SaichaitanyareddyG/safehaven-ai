import pytest

from app.instructions.models import CareInstruction, InstructionStatus
from app.instructions.state import ALLOWED_TRANSITIONS, InvalidTransitionError, assert_transition_allowed, transition

ALL_STATUSES = list(InstructionStatus)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (InstructionStatus.DRAFT, InstructionStatus.PROCESSING),
        (InstructionStatus.PROCESSING, InstructionStatus.NEEDS_REVIEW),
        (InstructionStatus.PROCESSING, InstructionStatus.READY_FOR_APPROVAL),
        (InstructionStatus.NEEDS_REVIEW, InstructionStatus.PROCESSING),
        (InstructionStatus.NEEDS_REVIEW, InstructionStatus.REJECTED),
        (InstructionStatus.READY_FOR_APPROVAL, InstructionStatus.APPROVED),
        (InstructionStatus.READY_FOR_APPROVAL, InstructionStatus.REJECTED),
        (InstructionStatus.READY_FOR_APPROVAL, InstructionStatus.NEEDS_REVIEW),
    ],
)
def test_allowed_transitions_do_not_raise(current, target):
    assert_transition_allowed(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (InstructionStatus.APPROVED, InstructionStatus.PROCESSING),
        (InstructionStatus.APPROVED, InstructionStatus.REJECTED),
        (InstructionStatus.APPROVED, InstructionStatus.NEEDS_REVIEW),
        (InstructionStatus.REJECTED, InstructionStatus.PROCESSING),
        (InstructionStatus.REJECTED, InstructionStatus.APPROVED),
        (InstructionStatus.DRAFT, InstructionStatus.NEEDS_REVIEW),
        (InstructionStatus.DRAFT, InstructionStatus.READY_FOR_APPROVAL),
        (InstructionStatus.DRAFT, InstructionStatus.APPROVED),
        (InstructionStatus.DRAFT, InstructionStatus.REJECTED),
        (InstructionStatus.PROCESSING, InstructionStatus.APPROVED),
        (InstructionStatus.PROCESSING, InstructionStatus.REJECTED),
        (InstructionStatus.PROCESSING, InstructionStatus.DRAFT),
        (InstructionStatus.NEEDS_REVIEW, InstructionStatus.APPROVED),
        (InstructionStatus.NEEDS_REVIEW, InstructionStatus.READY_FOR_APPROVAL),
        (InstructionStatus.READY_FOR_APPROVAL, InstructionStatus.PROCESSING),
        (InstructionStatus.READY_FOR_APPROVAL, InstructionStatus.DRAFT),
    ],
)
def test_disallowed_transitions_raise(current, target):
    with pytest.raises(InvalidTransitionError):
        assert_transition_allowed(current, target)


def test_every_status_has_an_explicit_entry_in_the_transition_table():
    """Guards against a future status being added to the enum without also adding
    it to ALLOWED_TRANSITIONS (a missing key silently defaults to "no transitions
    allowed", which could hide a bug rather than surface one)."""
    assert set(ALLOWED_TRANSITIONS.keys()) == set(ALL_STATUSES)


def test_terminal_statuses_allow_no_transitions():
    assert ALLOWED_TRANSITIONS[InstructionStatus.APPROVED] == set()
    assert ALLOWED_TRANSITIONS[InstructionStatus.REJECTED] == set()


def test_transition_mutates_status_on_success():
    instruction = CareInstruction(status=InstructionStatus.DRAFT)
    transition(instruction, InstructionStatus.PROCESSING)
    assert instruction.status == InstructionStatus.PROCESSING


def test_transition_does_not_mutate_status_on_failure():
    instruction = CareInstruction(status=InstructionStatus.APPROVED)
    with pytest.raises(InvalidTransitionError):
        transition(instruction, InstructionStatus.PROCESSING)
    assert instruction.status == InstructionStatus.APPROVED


def test_invalid_transition_error_message_names_both_statuses():
    error = InvalidTransitionError(InstructionStatus.APPROVED, InstructionStatus.PROCESSING)
    assert "APPROVED" in str(error)
    assert "PROCESSING" in str(error)
