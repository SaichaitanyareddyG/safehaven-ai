from app.instructions.models import CareInstruction, InstructionStatus


class InvalidTransitionError(Exception):
    def __init__(self, current: InstructionStatus, target: InstructionStatus):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition instruction from {current.value} to {target.value}")


# Single source of truth for which status graph edges are ever legal. Note that
# PROCESSING is a target shared by two different business operations — /submit
# (from DRAFT) and /clarify (from NEEDS_REVIEW) — this graph only says the edge is
# structurally legal; service.py additionally checks *which* operation is allowed to
# use it, since the graph alone can't distinguish caller intent for a shared target.
ALLOWED_TRANSITIONS: dict[InstructionStatus, set[InstructionStatus]] = {
    InstructionStatus.DRAFT: {InstructionStatus.PROCESSING},
    InstructionStatus.PROCESSING: {InstructionStatus.NEEDS_REVIEW, InstructionStatus.READY_FOR_APPROVAL},
    InstructionStatus.NEEDS_REVIEW: {InstructionStatus.PROCESSING, InstructionStatus.REJECTED},
    InstructionStatus.READY_FOR_APPROVAL: {
        InstructionStatus.APPROVED,
        InstructionStatus.REJECTED,
        InstructionStatus.NEEDS_REVIEW,
    },
    InstructionStatus.APPROVED: set(),
    InstructionStatus.REJECTED: set(),
}


def assert_transition_allowed(current: InstructionStatus, target: InstructionStatus) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(current, target)


def transition(instruction: CareInstruction, target: InstructionStatus) -> None:
    assert_transition_allowed(instruction.status, target)
    instruction.status = target
