"""Deterministic stand-in for a real LLM, used by default in tests (LLM_PROVIDER=mock).

Two ways to get a response, both deterministic (no network, no randomness):

1. Organic: for ordinary instruction text, a small regex/keyword engine classifies
   the instruction type and extracts only what's explicitly present in the text —
   deliberately unable to invent a value it has no textual evidence for, which
   makes it a faithful (if simple) stand-in for the "never invent" prompt rule a
   real provider is asked to follow.
2. Fixture markers: text containing "__FIXTURE__:<NAME>" selects a named canned
   scenario, checked by both extract_instruction (reading the instruction text)
   and generate_patient_friendly (reading original_text, so the same marker
   carries through from creation to generation). Extraction fixtures:
   COMPLETE_MEDICATION, INCOMPLETE_MEDICATION, COMPLETE_MOBILITY,
   INCOMPLETE_MOBILITY, MALFORMED_RESPONSE, PROVIDER_FAILURE. Generation
   fixtures: GENERATION_VALID, GENERATION_CHANGED_DOSE,
   GENERATION_CHANGED_FREQUENCY, GENERATION_CHANGED_MEDICATION_NAME,
   GENERATION_REMOVED_ROUTE, GENERATION_REMOVED_WARNING,
   GENERATION_ADDED_ASSISTANCE, GENERATION_REMOVED_ASSISTANCE,
   GENERATION_PROVIDER_FAILURE — each deliberately corrupts one fact before
   rendering, to exercise fact-preservation validation deterministically.
   Translation fixtures (TRANSLATION_CHANGED_DOSE, _CHANGED_FREQUENCY,
   _CHANGED_DURATION, _CHANGED_ASSISTANCE, _PROVIDER_FAILURE) are requested at
   a *later* API call than generation (POST .../translations, well after the
   English text already exists) — generate_patient_friendly passes any
   TRANSLATION_-prefixed marker through into its output text unmodified so it
   survives into patient_text_en, the only place translate_patient_text can
   still see it. Optionally prefix a language name — e.g.
   TRANSLATION_TELUGU_CHANGED_DOSE — to corrupt only that language's
   translation while others in the same request stay valid (needed to test
   e.g. "Telugu failure does not block Hindi/English").
"""

import re
import uuid

from app.ai.prompts import PATIENT_CHAT_DECLINE_MESSAGE
from app.ai.provider import (
    ChatTurn,
    ExtractionProviderError,
    ProviderMetadata,
    RawChatResponse,
    RawExtractionResponse,
    RawGenerationResponse,
    RawImageIdentificationResponse,
    RawTranslationResponse,
)
from app.instructions.models import InstructionType
from app.patients.models import Language

MODEL_NAME = "mock-extraction-v1"

_FIXTURE_MARKER_RE = re.compile(r"__FIXTURE__:(\w+)")

_FIXTURE_TEXT = {
    "COMPLETE_MEDICATION": "Take Metoprolol 25 mg orally twice daily with food.",
    "INCOMPLETE_MEDICATION": "Take Metoprolol.",
    "COMPLETE_MOBILITY": "Walk for 10 minutes after meals with nurse assistance.",
    "INCOMPLETE_MOBILITY": "Walk after meals.",
}

_DOSE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml)\b", re.IGNORECASE)
_DURATION_RE = re.compile(r"(\d+)\s*(?:minutes|minute|mins|min)\b", re.IGNORECASE)
# Medication course length ("for 3 days", "for 2 weeks") — a different concept
# from _DURATION_RE above (a single mobility session's length, in minutes).
# _REASON_RE's own negative lookahead already excludes "for <number>" so this
# doesn't get double-captured as a reason.
_MEDICATION_DURATION_RE = re.compile(r"\bfor\s+(\d+\s*(?:day|days|week|weeks))\b", re.IGNORECASE)
# Greedily captures consecutive capitalized words after "Take" — not just the
# first one — so a salt-form/release qualifier written as part of the name
# (e.g. "Take Metoprolol Succinate ER 25 mg...") is captured in full rather
# than truncated to just the base drug name. This matters for Module 2's
# formulation check (app/medication_verification/service.py), which can only
# compare what's actually in medication_name.
_MEDICATION_NAME_RE = re.compile(r"\bTake\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)")

_FREQUENCY_PATTERNS = [
    (re.compile(r"\btwice daily\b|\bBID\b", re.IGNORECASE), "twice daily"),
    (re.compile(r"\bthree times daily\b|\bTID\b", re.IGNORECASE), "three times daily"),
    (re.compile(r"\bonce daily\b|\bQD\b|\bdaily\b", re.IGNORECASE), "once daily"),
]
_ROUTE_PATTERNS = [
    # "by mouth" included because it's an expected, acceptable patient-facing
    # paraphrase of "orally"/"PO" (see the Step 6 generation prompt) — the mock's
    # re-extraction of generated text needs to recognize it too, or a perfectly
    # safe generation would spuriously fail fact-preservation validation.
    (re.compile(r"\borally\b|\bPO\b|\bby mouth\b", re.IGNORECASE), "oral"),
    (re.compile(r"\btopically\b", re.IGNORECASE), "topical"),
]
_ASSISTANCE_REQUIRED_TRUE_RE = re.compile(
    r"\bassistance\b|\bwith help\b|\bwith (?:your |a |the )?nurse\b", re.IGNORECASE
)
_ASSISTANCE_REQUIRED_FALSE_RE = re.compile(
    r"\bwithout assistance\b|\bno assistance\b|\bindependently\b|\bon (?:his|her|their|your) own\b",
    re.IGNORECASE,
)
# Matches an explicitly stated reason ("for your blood pressure", "to treat
# your infection", "to support your recovery") — deliberately simple, since
# this only needs to prove the "extract only if explicitly stated" behavior
# for tests, not model real-world phrasing variety. "for" is excluded when
# followed by a number ("for 7 days") — that's a duration, not a reason, and
# several existing test instructions use exactly that phrasing.
_REASON_RE = re.compile(
    r"\b(?:for(?!\s+\d)|to treat|to help(?: with| control| manage)?|to control|to support|to manage)\s+"
    r"((?:your|his|her|their)?\s*[a-zA-Z][a-zA-Z ]*?)(?=[.,]|$)",
    re.IGNORECASE,
)


def _extract_reason(text: str) -> str | None:
    match = _REASON_RE.search(text)
    if not match:
        return None
    reason = match.group(1).strip()
    return reason or None


class MockLLMProvider:
    def extract_instruction(self, text: str, context: dict | None = None) -> RawExtractionResponse:
        fixture_match = _FIXTURE_MARKER_RE.search(text)
        fixture_name = fixture_match.group(1) if fixture_match else None

        if fixture_name == "PROVIDER_FAILURE":
            raise ExtractionProviderError("Simulated provider failure (PROVIDER_FAILURE fixture)")

        if fixture_name == "MALFORMED_RESPONSE":
            # Deliberately the wrong shape (facts must be an object) so it fails
            # Pydantic validation downstream, exercising the malformed-output path.
            payload = {"instruction_type": "MEDICATION", "facts": "not-an-object", "ambiguities": []}
        elif fixture_name in _FIXTURE_TEXT:
            payload = _classify_and_extract(_FIXTURE_TEXT[fixture_name])
        else:
            payload = _classify_and_extract(text)

        return RawExtractionResponse(
            payload=payload,
            metadata=ProviderMetadata(
                provider="mock",
                model=MODEL_NAME,
                request_id=f"mock-{uuid.uuid4()}",
                latency_ms=5,
                token_usage={"prompt_tokens": 0, "completion_tokens": 0},
            ),
        )

    def generate_patient_friendly(
        self, original_text: str, structured_facts: dict, instruction_type: InstructionType
    ) -> RawGenerationResponse:
        fixture_match = _FIXTURE_MARKER_RE.search(original_text)
        fixture_name = fixture_match.group(1) if fixture_match else None

        if fixture_name == "GENERATION_PROVIDER_FAILURE":
            raise ExtractionProviderError(
                "Simulated generation provider failure (GENERATION_PROVIDER_FAILURE fixture)"
            )

        facts = dict(structured_facts)
        if fixture_name == "GENERATION_CHANGED_DOSE" and facts.get("dose_value") is not None:
            facts["dose_value"] = facts["dose_value"] * 2
        elif fixture_name == "GENERATION_CHANGED_FREQUENCY":
            facts["frequency"] = "once daily" if facts.get("frequency") != "once daily" else "three times daily"
        elif fixture_name == "GENERATION_CHANGED_MEDICATION_NAME":
            facts["medication_name"] = "Atenolol" if facts.get("medication_name") != "Atenolol" else "Lisinopril"
        elif fixture_name == "GENERATION_REMOVED_ROUTE":
            facts["route"] = None
        elif fixture_name == "GENERATION_REMOVED_WARNING":
            facts["warnings"] = []
        elif fixture_name == "GENERATION_ADDED_ASSISTANCE":
            facts["assistance_required"] = True
        elif fixture_name == "GENERATION_REMOVED_ASSISTANCE":
            facts["assistance_required"] = False
        # GENERATION_VALID and any unrecognized/absent marker: render facts as-is.

        text = _render_patient_text(facts, instruction_type)

        if fixture_name == "GENERATION_REEXTRACTION_MALFORMED":
            # Generation itself succeeds; the malformed marker is embedded in the
            # *output* text so it's the follow-up re-extraction call (Layer B)
            # that hits the malformed-response path, not this call.
            text += " __FIXTURE__:MALFORMED_RESPONSE"
        elif fixture_name and fixture_name.startswith("TRANSLATION_"):
            # Not generation's concern — pass it through unmodified so it's
            # still visible to translate_patient_text, called much later against
            # patient_text_en (see module docstring).
            text += f" __FIXTURE__:{fixture_name}"

        return RawGenerationResponse(
            patient_text=text,
            metadata=ProviderMetadata(
                provider="mock",
                model=MODEL_NAME,
                request_id=f"mock-{uuid.uuid4()}",
                latency_ms=5,
                token_usage={"prompt_tokens": 0, "completion_tokens": 0},
            ),
        )

    def translate_patient_text(
        self, text: str, target_language: Language, structured_facts: dict
    ) -> RawTranslationResponse:
        fixture_match = _FIXTURE_MARKER_RE.search(text)
        fixture_name = fixture_match.group(1) if fixture_match else None
        # A marker may name a specific language (TRANSLATION_TELUGU_CHANGED_DOSE)
        # so a single translation request covering multiple languages can
        # deterministically make just one of them fail — needed to test "Telugu
        # failure does not block Hindi/English" independently of the others.
        # An unprefixed marker (TRANSLATION_CHANGED_DOSE) applies to every
        # requested language.
        fixture_language, fixture_corruption = _parse_translation_fixture(fixture_name)
        applies_here = fixture_language is None or fixture_language == target_language

        if applies_here and fixture_corruption == "PROVIDER_FAILURE":
            raise ExtractionProviderError(
                f"Simulated translation provider failure ({fixture_name} fixture)"
            )

        # Strip the fixture marker itself (and any prior language tag, if this
        # call is a back-translation of an already-tagged translation) before
        # working with the text.
        base_text = _FIXTURE_MARKER_RE.sub("", text).strip()
        base_text = _strip_translation_tag(base_text)

        if target_language == Language.ENGLISH:
            # Back-translation: recover the underlying English content exactly
            # as this mock "translated" it — corruption included, if any.
            translated = base_text
        else:
            corrupted = _apply_translation_corruption(
                base_text, structured_facts, fixture_corruption if applies_here else None
            )
            translated = f"[{_LANGUAGE_TAGS[target_language]}] {corrupted}"

        return RawTranslationResponse(
            translated_text=translated,
            metadata=ProviderMetadata(
                provider="mock",
                model=MODEL_NAME,
                request_id=f"mock-{uuid.uuid4()}",
                latency_ms=5,
                token_usage={"prompt_tokens": 0, "completion_tokens": 0},
            ),
        )

    def chat_with_patient(self, care_plan_summary: str, history: list[ChatTurn]) -> RawChatResponse:
        # __UNGROUNDED_QUESTION__ deterministically simulates "neither the
        # approved context nor web search covers this" (the real model is
        # instructed to give the fixed decline verbatim in that case — see
        # PATIENT_CHAT_SYSTEM_PROMPT) without relying on a fragile guess at
        # what counts as "related" to the care plan text.
        # __WEB_SEARCH_QUESTION__ deterministically simulates the model
        # having used the trusted-source web search tool to answer — mirrors
        # what only the real OpenAI provider can actually do.
        last_message = history[-1].text.strip() if history else ""
        web_search_used = False
        if "__UNGROUNDED_QUESTION__" in last_message:
            reply = PATIENT_CHAT_DECLINE_MESSAGE
        elif "__WEB_SEARCH_QUESTION__" in last_message:
            web_search_used = True
            reply = "[MOCK CHAT REPLY, general medical sources] This is general reference information, not specific to your care plan."
        else:
            reply = f"[MOCK CHAT REPLY] Based on your care plan: {care_plan_summary.strip()[:200]}"
        return RawChatResponse(
            reply_text=reply,
            metadata=ProviderMetadata(
                provider="mock",
                model=MODEL_NAME,
                request_id=f"mock-{uuid.uuid4()}",
                latency_ms=5,
                token_usage={"prompt_tokens": 0, "completion_tokens": 0},
            ),
            web_search_used=web_search_used,
        )

    def identify_medication_from_image(self, image_bytes: bytes, mime_type: str) -> RawImageIdentificationResponse:
        # Tests send a small marker byte string in place of a real photo —
        # __FIXTURE_IMAGE__:<NAME> — same convention as the text fixture
        # markers elsewhere in this file, since there is no real image to
        # decode in a deterministic test double. Fixtures: SUCCINATE_25,
        # TARTRATE_25 (both "high" confidence, fully legible), BLURRY (a
        # partial, low-confidence reading — medication name only), UNREADABLE
        # (nothing legible at all), PROVIDER_FAILURE.
        if b"__FIXTURE_IMAGE__:PROVIDER_FAILURE" in image_bytes:
            raise ExtractionProviderError("Simulated provider failure (PROVIDER_FAILURE fixture)")

        if b"__FIXTURE_IMAGE__:SUCCINATE_25" in image_bytes:
            fields = {
                "medication_name": "Metoprolol Succinate ER",
                "strength_value": 25.0,
                "strength_unit": "mg",
                "formulation": "extended-release tablet",
                "route": "oral",
                "confidence": "high",
            }
        elif b"__FIXTURE_IMAGE__:TARTRATE_25" in image_bytes:
            fields = {
                "medication_name": "Metoprolol Tartrate",
                "strength_value": 25.0,
                "strength_unit": "mg",
                "formulation": "immediate-release tablet",
                "route": "oral",
                "confidence": "high",
            }
        elif b"__FIXTURE_IMAGE__:BLURRY" in image_bytes:
            fields = {
                "medication_name": "Metoprolol",
                "strength_value": None,
                "strength_unit": None,
                "formulation": None,
                "route": None,
                "confidence": "low",
            }
        else:
            # Default / __FIXTURE_IMAGE__:UNREADABLE — nothing legible.
            fields = {
                "medication_name": None,
                "strength_value": None,
                "strength_unit": None,
                "formulation": None,
                "route": None,
                "confidence": "low",
            }

        return RawImageIdentificationResponse(
            **fields,
            metadata=ProviderMetadata(
                provider="mock",
                model=MODEL_NAME,
                request_id=f"mock-{uuid.uuid4()}",
                latency_ms=5,
                token_usage={"prompt_tokens": 0, "completion_tokens": 0},
            ),
        )


def _classify_instruction_type(text: str) -> InstructionType:
    lowered = text.lower()
    if _DOSE_RE.search(text) or "take" in lowered or "tablet" in lowered:
        return InstructionType.MEDICATION
    if "walk" in lowered or "exercise" in lowered or "mobility" in lowered:
        return InstructionType.MOBILITY
    if "wound" in lowered or "dressing" in lowered or "bandage" in lowered:
        return InstructionType.WOUND_CARE
    if "follow up" in lowered or "follow-up" in lowered or "appointment" in lowered or "see dr" in lowered:
        return InstructionType.FOLLOW_UP
    if "eat" in lowered or "diet" in lowered or "avoid" in lowered or "fluid" in lowered:
        return InstructionType.DIET
    return InstructionType.GENERAL


def _extract_medication_facts(text: str) -> dict:
    dose_match = _DOSE_RE.search(text)
    frequency = next((label for pattern, label in _FREQUENCY_PATTERNS if pattern.search(text)), None)
    route = next((label for pattern, label in _ROUTE_PATTERNS if pattern.search(text)), None)
    if re.search(r"\bwith food\b", text, re.IGNORECASE):
        with_food = True
    elif re.search(r"\bwithout food\b", text, re.IGNORECASE):
        with_food = False
    else:
        with_food = None
    name_match = _MEDICATION_NAME_RE.search(text)
    duration_match = _MEDICATION_DURATION_RE.search(text)

    return {
        "medication_name": name_match.group(1) if name_match else None,
        "dose_value": float(dose_match.group(1)) if dose_match else None,
        "dose_unit": dose_match.group(2).lower() if dose_match else None,
        "route": route,
        "frequency": frequency,
        "timing": None,
        "duration": duration_match.group(1).strip() if duration_match else None,
        "with_food": with_food,
        "warnings": [],
        "reason": _extract_reason(text),
    }


def _extract_mobility_facts(text: str) -> dict:
    lowered = text.lower()
    duration_match = _DURATION_RE.search(text)
    if _ASSISTANCE_REQUIRED_FALSE_RE.search(text):
        assistance_required = False
    elif _ASSISTANCE_REQUIRED_TRUE_RE.search(text):
        assistance_required = True
    else:
        assistance_required = None

    return {
        "activity": "walking" if "walk" in lowered else None,
        "timing": "after meals" if "after meals" in lowered else None,
        "duration": f"{duration_match.group(1)} minutes" if duration_match else None,
        "assistance_required": assistance_required,
        "restrictions": [],
        "reason": _extract_reason(text),
    }


def _extract_diet_facts(text: str) -> dict:
    return {
        "allowed_intake": [],
        "restricted_intake": [],
        "timing": None,
        "special_restrictions": [],
        "reason": _extract_reason(text),
    }


def _extract_wound_care_facts(text: str) -> dict:
    return {
        "body_site": None,
        "action": None,
        "frequency": None,
        "supplies": [],
        "warning_signs": [],
        "reason": _extract_reason(text),
    }


def _extract_follow_up_facts(text: str) -> dict:
    return {"provider_or_specialty": None, "timeframe": None, "purpose": None}


_EXTRACTORS = {
    InstructionType.MEDICATION: _extract_medication_facts,
    InstructionType.MOBILITY: _extract_mobility_facts,
    InstructionType.DIET: _extract_diet_facts,
    InstructionType.WOUND_CARE: _extract_wound_care_facts,
    InstructionType.FOLLOW_UP: _extract_follow_up_facts,
}


def _classify_and_extract(text: str) -> dict:
    instruction_type = _classify_instruction_type(text)
    extractor = _EXTRACTORS.get(instruction_type)
    facts = extractor(text) if extractor else {"summary": text.strip(), "details": []}
    return {"instruction_type": instruction_type.value, "facts": facts, "ambiguities": []}


# ---------------------------------------------------------------------------
# Deterministic patient-text rendering (Step 6). Templates facts directly into
# a sentence rather than "creatively" rewriting the original text — this makes
# fact preservation correct by construction for the untouched (GENERATION_VALID)
# case, and vocabulary is deliberately chosen to round-trip through the same
# extraction engine above (e.g. "by mouth" is recognized by _ROUTE_PATTERNS),
# so a genuinely faithful rendering doesn't spuriously fail re-extraction.
# ---------------------------------------------------------------------------


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _render_medication_text(facts: dict) -> str:
    name = facts.get("medication_name") or "this medication"
    dose_value = facts.get("dose_value")
    dose_unit = facts.get("dose_unit")
    route = facts.get("route")
    frequency = facts.get("frequency")
    duration = facts.get("duration")
    with_food = facts.get("with_food")
    warnings = facts.get("warnings") or []

    sentence = f"Take {name}"
    if dose_value is not None:
        sentence += f" {_format_number(dose_value)}"
        if dose_unit:
            sentence += f" {dose_unit}"
    if route == "oral":
        sentence += " by mouth"
    elif route:
        sentence += f" {route}"
    if frequency:
        sentence += f" {frequency}"
    if duration:
        sentence += f" for {duration}"
    sentence += "."

    parts = [sentence]
    if with_food is True:
        parts.append("Take it with food.")
    elif with_food is False:
        parts.append("Take it without food.")
    # "reason" deliberately never appears here — see FIELDS_BY_TYPE's comment
    # in validation/fact_preservation.py. It's shown separately, in the care
    # plan's own "why" section (patient_access/service.py).
    parts.extend(warnings)
    return " ".join(parts)


def _render_mobility_text(facts: dict) -> str:
    activity = (facts.get("activity") or "the activity").capitalize()
    timing = facts.get("timing")
    duration = facts.get("duration")
    assistance_required = facts.get("assistance_required")
    restrictions = facts.get("restrictions") or []

    sentence = activity
    if duration:
        sentence += f" for {duration}"
    if timing:
        sentence += f" {timing}"
    if assistance_required is True:
        sentence += " with your nurse"
    elif assistance_required is False:
        sentence += " on your own"
    sentence += "."

    # "reason" deliberately never appears here — see the medication renderer's
    # comment above.
    return " ".join([sentence, *restrictions])


def _render_generic_text(facts: dict) -> str:
    parts = [f"{field.replace('_', ' ')}: {value}" for field, value in facts.items() if value not in (None, "", [])]
    return (". ".join(parts) + ".") if parts else "Please follow your care team's instructions."


_RENDERERS = {
    InstructionType.MEDICATION: _render_medication_text,
    InstructionType.MOBILITY: _render_mobility_text,
}


def _render_patient_text(facts: dict, instruction_type: InstructionType) -> str:
    renderer = _RENDERERS.get(instruction_type)
    return renderer(facts) if renderer else _render_generic_text(facts)


# ---------------------------------------------------------------------------
# Deterministic "translation" (Step 8). This mock doesn't do real translation —
# it wraps the exact same English content in a language tag, so the safety
# pipeline (dose/warning scans, back-translation + re-extraction + structured
# comparison) has real, round-trippable text to work with. A genuine provider's
# translation is checked by that same pipeline regardless of what the text
# actually looks like — this mock's honesty about not being real Telugu/Hindi
# doesn't weaken the validation being exercised.
# ---------------------------------------------------------------------------

_LANGUAGE_TAGS = {Language.TELUGU: "TELUGU_TR", Language.HINDI: "HINDI_TR"}
_LANGUAGE_TAG_RE = re.compile(r"^\[(?:TELUGU_TR|HINDI_TR)\]\s*")
_FIXTURE_LANGUAGE_PREFIXES = {"TELUGU": Language.TELUGU, "HINDI": Language.HINDI}


def _strip_translation_tag(text: str) -> str:
    return _LANGUAGE_TAG_RE.sub("", text)


def _parse_translation_fixture(fixture_name: str | None) -> tuple[Language | None, str | None]:
    """"TRANSLATION_TELUGU_CHANGED_DOSE" -> (Language.TELUGU, "CHANGED_DOSE").
    "TRANSLATION_CHANGED_DOSE" (no language segment) -> (None, "CHANGED_DOSE"),
    meaning it applies to whichever language is currently being translated."""
    if not fixture_name or not fixture_name.startswith("TRANSLATION_"):
        return None, None
    rest = fixture_name[len("TRANSLATION_") :]
    for lang_name, language in _FIXTURE_LANGUAGE_PREFIXES.items():
        prefix = f"{lang_name}_"
        if rest.startswith(prefix):
            return language, rest[len(prefix) :]
    return None, rest


def _apply_translation_corruption(text: str, facts: dict, corruption: str | None) -> str:
    """`corruption` is the fixture name with any "TRANSLATION_" / language
    prefix already stripped by _parse_translation_fixture — e.g. "CHANGED_DOSE"."""
    if corruption == "CHANGED_DOSE":
        dose_value = facts.get("dose_value")
        if dose_value is not None:
            old_str = _format_number(dose_value)
            new_str = _format_number(dose_value * 2)
            replaced = re.sub(rf"\b{re.escape(old_str)}\b", new_str, text, count=1)
            if replaced != text:
                return replaced
    elif corruption == "CHANGED_FREQUENCY":
        if "twice daily" in text:
            return text.replace("twice daily", "once daily")
        if "once daily" in text:
            return text.replace("once daily", "three times daily")
    elif corruption == "CHANGED_DURATION":
        match = re.search(r"(\d+) minutes", text)
        if match:
            return text.replace(f"{match.group(1)} minutes", f"{int(match.group(1)) + 5} minutes", 1)
    elif corruption == "CHANGED_ASSISTANCE":
        if "with your nurse" in text:
            return text.replace("with your nurse", "on your own")
        if "on your own" in text:
            return text.replace("on your own", "with your nurse")
    return text
