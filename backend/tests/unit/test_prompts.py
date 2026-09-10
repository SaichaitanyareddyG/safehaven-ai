"""Regression test for a real bug found during Step 10 real-LLM evaluation:
the extraction tool schema's "facts" property used to be a bare {"type":
"object"}, with no declared sub-fields, relying entirely on prose to convey
field names. Under real-model testing, this let a model silently invent its
own field names (e.g. "dose" instead of "dose_value"), which were then
silently dropped by MedicationFacts et al. (Pydantic ignores unknown fields by
default) — the correct value never reached the app at all, not even as an
incorrect one. This test locks the schema to explicitly, exhaustively name
every field every *Facts model expects, so this can't regress silently.
"""

from app.ai.prompts import EXTRACTION_TOOL_SCHEMA
from app.ai.schemas import (
    DietFacts,
    FollowUpFacts,
    GeneralFacts,
    MedicationFacts,
    MobilityFacts,
    WoundCareFacts,
)

ALL_FACT_MODELS = [
    MedicationFacts,
    MobilityFacts,
    DietFacts,
    WoundCareFacts,
    FollowUpFacts,
    GeneralFacts,
]


def test_facts_schema_declares_explicit_properties():
    facts_schema = EXTRACTION_TOOL_SCHEMA["properties"]["facts"]
    assert facts_schema.get("properties"), "facts schema must enumerate its fields, not be a bare object"


def test_facts_schema_covers_every_field_of_every_instruction_type():
    declared_fields = set(EXTRACTION_TOOL_SCHEMA["properties"]["facts"]["properties"].keys())
    expected_fields = {
        field_name for model in ALL_FACT_MODELS for field_name in model.model_fields.keys()
    }
    missing = expected_fields - declared_fields
    assert not missing, f"Schema is missing fields the app's own Facts models expect: {missing}"


def test_facts_schema_rejects_unknown_field_names():
    facts_schema = EXTRACTION_TOOL_SCHEMA["properties"]["facts"]
    assert facts_schema.get("additionalProperties") is False, (
        "facts schema must set additionalProperties: false so a model can't silently invent "
        "synonym field names (e.g. 'dose' instead of 'dose_value') that then get dropped"
    )
