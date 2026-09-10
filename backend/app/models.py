"""Central model registration.

Importing this module guarantees every SQLAlchemy model is loaded and registered
on Base.metadata, which mapper/relationship resolution needs. Alembic (env.py) and
any standalone script or test that needs the full schema should import this module
instead of importing individual models/router modules — main.py should not be a
back-door way to get ORM models registered.
"""

from app.auth.models import User  # noqa: F401
from app.audit.models import AuditEvent  # noqa: F401
from app.conditions.models import PatientCondition  # noqa: F401
from app.encounters.models import Encounter  # noqa: F401
from app.patients.models import Patient  # noqa: F401
from app.instructions.models import (  # noqa: F401
    CareInstruction,
    InstructionVersion,
    PatientOutput,
    PatientOutputTranslation,
    StructuredExtraction,
)
from app.medication_verification.models import AdministrationEvent  # noqa: F401
from app.patient_access.models import PatientCareAccessToken  # noqa: F401
from app.patient_chat.models import PatientChatMessage  # noqa: F401
from app.patient_feedback.models import PatientComprehensionFeedback  # noqa: F401
