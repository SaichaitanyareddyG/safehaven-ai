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
medication_name + dose alone (see the verification engine)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MedicationProduct:
    barcode: str
    medication_name: str
    strength_value: float
    strength_unit: str
    formulation: str
    route: str


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
}


def lookup_medication_product(barcode: str | None) -> MedicationProduct | None:
    if not barcode:
        return None
    return MEDICATION_PRODUCTS.get(barcode.strip())
