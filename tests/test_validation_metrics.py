"""Phase 7A: metric formulas verified against hand calculations."""

import pytest

from services.validation import metrics as metrics_mod


def test_binary_hand_fixture_tp8_tn7_fp2_fn3():
    """Spec example: Accuracy=15/20, Precision=8/10, Recall=8/11,
    Specificity=7/9, F1=16/21."""
    m = metrics_mod.binary_metrics(tp=8, tn=7, fp=2, fn=3)
    assert m["N"] == 20
    assert m["accuracy"]["value"] == pytest.approx(15 / 20)
    assert m["precision"]["value"] == pytest.approx(8 / 10)
    assert m["recall"]["value"] == pytest.approx(8 / 11)
    assert m["specificity"]["value"] == pytest.approx(7 / 9)
    assert m["f1"]["value"] == pytest.approx(16 / 21)
    assert all(m[k]["status"] == "OK" for k in
               ("accuracy", "precision", "recall", "specificity", "f1"))
    # Full precision stored (not pre-rounded).
    assert m["recall"]["value"] != 0.73


def test_binary_zero_denominators_are_undefined_not_zero():
    m = metrics_mod.binary_metrics(tp=0, tn=5, fp=0, fn=3)
    assert m["precision"]["value"] is None
    assert m["precision"]["status"] == "UNDEFINED"
    assert "No positive system predictions" in m["precision"]["reason"]
    assert m["recall"]["value"] == pytest.approx(0.0)  # defined: 0/3
    assert m["f1"]["value"] is None  # precision undefined -> F1 undefined
    m2 = metrics_mod.binary_metrics(tp=0, tn=0, fp=0, fn=0)
    assert m2["accuracy"]["status"] == "UNDEFINED"
    m3 = metrics_mod.binary_metrics(tp=2, tn=0, fp=0, fn=1)
    assert m3["specificity"]["status"] == "UNDEFINED"
    assert m3["specificity"]["value"] is None


def test_multiclass_hand_fixture():
    labels = ["WEAK", "MODERATE", "STRONG"]
    pairs = [
        ("WEAK", "WEAK", "s1"), ("WEAK", "WEAK", "s2"),
        ("MODERATE", "MODERATE", "s3"), ("MODERATE", "MODERATE", "s4"),
        ("STRONG", "STRONG", "s5"), ("STRONG", "MODERATE", "s6"),
    ]
    m = metrics_mod.multiclass_metrics(pairs, labels)
    assert m["N"] == 6
    assert m["accuracy"]["value"] == pytest.approx(5 / 6)
    weak = m["per_class"]["WEAK"]
    assert (weak["precision"]["value"], weak["recall"]["value"],
            weak["f1"]["value"], weak["support"]) == (1.0, 1.0, 1.0, 2)
    mod = m["per_class"]["MODERATE"]
    assert mod["precision"]["value"] == pytest.approx(2 / 3)
    assert mod["recall"]["value"] == pytest.approx(1.0)
    assert mod["f1"]["value"] == pytest.approx(0.8)
    strong = m["per_class"]["STRONG"]
    assert strong["precision"]["value"] == pytest.approx(1.0)
    assert strong["recall"]["value"] == pytest.approx(0.5)
    assert strong["f1"]["value"] == pytest.approx(2 / 3)
    assert m["macro_precision"]["value"] == pytest.approx(8 / 9)
    assert m["macro_recall"]["value"] == pytest.approx(2.5 / 3)
    assert m["weighted_f1"]["value"] == pytest.approx(m["macro_f1"]["value"])
    # Orientation + raw IDs.
    cells = m["matrix"]["cells"]
    assert m["matrix"]["orientation"].startswith("rows=system")
    assert cells["MODERATE"]["STRONG"]["sample_ids"] == ["s6"]
    assert cells["STRONG"]["STRONG"]["count"] == 1


def test_multiclass_empty_class_undefined():
    labels = ["WEAK", "MODERATE", "STRONG"]
    pairs = [("WEAK", "WEAK", "s1"), ("MODERATE", "MODERATE", "s2")]
    m = metrics_mod.multiclass_metrics(pairs, labels)
    assert m["per_class"]["STRONG"]["precision"]["status"] == "UNDEFINED"
    assert m["per_class"]["STRONG"]["precision"]["value"] is None
    assert m["macro_precision"]["value"] == pytest.approx((1 + 1) / 2)


def test_sklearn_crosscheck_matches_manual():
    labels = ["WEAK", "MODERATE", "STRONG"]
    pairs = [("WEAK", "WEAK"), ("WEAK", "MODERATE"), ("MODERATE", "MODERATE"),
             ("STRONG", "STRONG"), ("STRONG", "MODERATE"), ("MODERATE", "WEAK")]
    check = metrics_mod.sklearn_crosscheck(pairs, labels)
    assert check["status"] == "OK"
    assert check["match"] is True
    assert max(d for d in check["differences"].values()
               if d is not None) <= 1e-9


def test_kappa_hand_calculation():
    # A: Y Y Y N N | B: Y Y N N N -> Po=0.8, Pe=0.48 -> k=0.32/0.52
    a = ["Y", "Y", "Y", "N", "N"]
    b = ["Y", "Y", "N", "N", "N"]
    k = metrics_mod.cohens_kappa(a, b)
    assert k["status"] == "OK"
    # Po=4/5=0.8; Pe=0.6*0.4+0.4*0.6=0.48 -> k=0.32/0.52
    assert k["value"] == pytest.approx((0.8 - 0.48) / 0.52)
    assert metrics_mod.cohens_kappa(["Y"], ["Y"])["status"] == "N/A"
    assert metrics_mod.cohens_kappa([], [])["status"] == "N/A"


def test_class_balance_flags_imbalance():
    pairs = [("A", "A")] * 9 + [("B", "B")]
    bal = metrics_mod.class_balance(pairs)
    assert bal["N"] == 10
    assert bal["counts"] == {"A": 9, "B": 1}
    assert bal["imbalance_warning"] is True
    bal2 = metrics_mod.class_balance([("A", "A")] * 3 + [("B", "B")] * 3)
    assert bal2["imbalance_warning"] is False
