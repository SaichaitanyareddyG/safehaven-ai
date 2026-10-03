from app.reference.medication_purpose import generic_name, lookup_medication_purpose


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



def test_brand_names_and_label_strengths_find_the_medicine():
    assert generic_name("DOLO") == "paracetamol"
    assert generic_name("Dolo 650") == "paracetamol"
    assert generic_name("Tylenol Extra Strength") == "acetaminophen"
    assert generic_name("Paracetamol 500 mg tablets") == "paracetamol"
    assert generic_name("Metoprolol succinate ER") == "metoprolol"
    assert lookup_medication_purpose("DOLO 650").startswith("Commonly used to relieve")


def test_combination_products_and_unknown_names_get_nothing():
    assert generic_name("Tylenol PM") is None  # also contains a sleep aid
    assert generic_name("Xyzzy") is None
    assert lookup_medication_purpose(None) is None
