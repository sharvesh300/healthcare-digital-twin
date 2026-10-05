from twin.clinical.measures import MEASURES, flag, measure_for


def test_single_analyte_flags():
    assert flag(MEASURES["hba1c"], {"hba1c": 6.6}) == "high"
    assert flag(MEASURES["hba1c"], {"hba1c": 5.2}) == "normal"
    assert flag(MEASURES["hdl"], {"hdl": 35}) == "low"
    assert flag(MEASURES["weight"], {"weight": 80}) is None  # no range
    assert flag(MEASURES["hba1c"], {}) is None


def test_sex_specific_ranges():
    m = MEASURES["hemoglobin"]
    assert flag(m, {"hemoglobin": 13.0}, "female") == "normal"
    assert flag(m, {"hemoglobin": 13.0}, "male") == "low"
    assert flag(m, {"hemoglobin": 13.0}, None) is None  # no sex, no range


def test_blood_pressure_is_flagged_per_component():
    bp = MEASURES["blood_pressure"]
    assert bp.analytes == ("sbp", "dbp")
    assert flag(bp, {"sbp": 118, "dbp": 76}) == "normal"
    assert flag(bp, {"sbp": 124, "dbp": 84}) == "high"  # diastolic alone is enough
    assert flag(bp, {"sbp": 135}) == "high"


def test_unknown_analytes_fall_under_other():
    m = measure_for("ferritin", "Ferritin [Mass/volume] in Serum")
    assert (m.key, m.panel, m.display) == ("ferritin", "other", "Ferritin [Mass/volume] in Serum")
    assert measure_for("dbp").key == "blood_pressure"
