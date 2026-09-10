from app.reference.medication_purpose import lookup_medication_purpose


def test_known_medication_returns_general_purpose():
    result = lookup_medication_purpose("Metoprolol")
    assert result is not None
    assert "blood pressure" in result.lower()


def test_lookup_is_case_insensitive():
    assert lookup_medication_purpose("metoprolol") == lookup_medication_purpose("METOPROLOL")


def test_unknown_medication_returns_none_never_a_guess():
    assert lookup_medication_purpose("SomeMadeUpDrugXYZ") is None


def test_none_medication_name_returns_none():
    assert lookup_medication_purpose(None) is None
