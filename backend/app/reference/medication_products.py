"""Static, curated reference mapping from a scanned barcode to the physical
medication product it identifies — Module 2's equivalent of
medication_purpose.py, and deliberately built the same way: a small,
hand-curated, non-patient-specific dict, not a database table. See
MODULE_2_DESIGN_REPORT.md section 5 for why — this project already has a
directly analogous case (MedicationPurposeCache, a DB table for exactly this
shape of static reference data, was built and then deliberately removed in
favor of a static dict).

The barcode is identification only, never the safety decision — see
app/medication_verification/service.py, which always compares the resolved
product against the patient's current active order before anything is
called VERIFIED.

formulation is what distinguishes e.g. Metoprolol Succinate ER (extended-
release) from Metoprolol Tartrate (immediate-release) — same drug name and
strength, clinically different products. Never collapse comparison to
medication_name + dose alone (see the verification engine).

high_alert flags a product on ISMP's List of High-Alert Medications in Acute
Care Settings (anticoagulants, insulin, opioids, concentrated electrolytes,
etc.) — drugs that cause disproportionate harm when administration goes
wrong. See medication_verification/service.py's administer() for what this
actually gates (an independent second-clinician co-sign, ISMP's recommended
mitigation), and US_HOSPITAL_MARKET_STANDARDS_GAP_ANALYSIS.md item 3 for the
full rationale."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MedicationProduct:
    barcode: str
    medication_name: str
    strength_value: float
    strength_unit: str
    formulation: str
    route: str
    high_alert: bool = False


# Keyed by the exact scanned barcode string (case-sensitive — barcodes are
# printed as exact strings, unlike medication_purpose.py's free-text lookup).
MEDICATION_PRODUCTS: dict[str, MedicationProduct] = {
    "MED-METOPROLOL-SUCCINATE-25": MedicationProduct(
        barcode="MED-METOPROLOL-SUCCINATE-25",
        medication_name="Metoprolol Succinate ER",
        strength_value=25.0,
        strength_unit="mg",
        formulation="extended-release tablet",
        route="oral",
    ),
    "MED-METOPROLOL-SUCCINATE-50": MedicationProduct(
        barcode="MED-METOPROLOL-SUCCINATE-50",
        medication_name="Metoprolol Succinate ER",
        strength_value=50.0,
        strength_unit="mg",
        formulation="extended-release tablet",
        route="oral",
    ),
    "MED-METOPROLOL-TARTRATE-25": MedicationProduct(
        barcode="MED-METOPROLOL-TARTRATE-25",
        medication_name="Metoprolol Tartrate",
        strength_value=25.0,
        strength_unit="mg",
        formulation="immediate-release tablet",
        route="oral",
    ),
    "MED-LISINOPRIL-10": MedicationProduct(
        barcode="MED-LISINOPRIL-10",
        medication_name="Lisinopril",
        strength_value=10.0,
        strength_unit="mg",
        formulation="immediate-release tablet",
        route="oral",
    ),
    "MED-METFORMIN-500": MedicationProduct(
        barcode="MED-METFORMIN-500",
        medication_name="Metformin",
        strength_value=500.0,
        strength_unit="mg",
        formulation="immediate-release tablet",
        route="oral",
    ),
    "MED-PARACETAMOL-500": MedicationProduct(
        barcode="MED-PARACETAMOL-500",
        medication_name="Paracetamol",
        strength_value=500.0,
        strength_unit="mg",
        formulation="immediate-release tablet",
        route="oral",
    ),
    # Subcutaneous, and deliberately so: a nil-by-mouth patient still receives
    # injected medication, which is what makes the NPO check route-aware
    # rather than a blanket block (see _check_nil_by_mouth).
    "MED-ENOXAPARIN-40": MedicationProduct(
        barcode="MED-ENOXAPARIN-40",
        medication_name="Enoxaparin",
        strength_value=40.0,
        strength_unit="mg",
        formulation="prefilled syringe",
        route="subcutaneous",
        high_alert=True,  # anticoagulant — ISMP high-alert medication
    ),
    "MED-WARFARIN-5": MedicationProduct(
        barcode="MED-WARFARIN-5",
        medication_name="Warfarin",
        strength_value=5.0,
        strength_unit="mg",
        formulation="immediate-release tablet",
        route="oral",
        high_alert=True,  # anticoagulant — ISMP high-alert medication
    ),
}


def lookup_medication_product(barcode: str | None) -> MedicationProduct | None:
    if not barcode:
        return None
    return MEDICATION_PRODUCTS.get(barcode.strip())


def formulations_for_drug_family(medication_name: str | None) -> set[str]:
    """Every distinct formulation this catalog stocks for a drug family, keyed
    on the base drug name (first word — "Metoprolol" out of "Metoprolol
    Succinate ER"), matching _drug_family_matches' convention in the
    verification engine.

    Used to answer the only question that actually matters when an order
    didn't state a formulation: *could this scan be confused with a different
    formulation of the same drug?* For Metoprolol the answer is yes (Succinate
    ER and Tartrate are both stocked, and mixing them up is exactly the error
    the formulation check exists to catch). For Lisinopril it is no — there is
    nothing else to confuse it with.

    This is answerable precisely because the catalog is a CLOSED WORLD: a
    product that isn't in it cannot be scanned at all (an unrecognized barcode
    returns PRODUCT_NOT_FOUND → REVIEW_REQUIRED long before any formulation
    comparison happens). And it self-maintains — the day a second Lisinopril
    formulation is added here, the ambiguity check starts applying to
    Lisinopril again with no code change."""
    if not medication_name:
        return set()
    base = medication_name.split()[0].strip().lower()
    return {
        product.formulation
        for product in MEDICATION_PRODUCTS.values()
        if product.medication_name.split()[0].strip().lower() == base
    }
