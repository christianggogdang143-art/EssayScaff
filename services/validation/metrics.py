"""Phase 7A metric formulas — centralized and documented.

All detector-performance formulas live here (project rule 10).
Full precision is stored; display rounding happens only in the UI.

Zero denominators are NEVER returned as fake zeros: value None,
status UNDEFINED, with a documented reason.
"""

from __future__ import annotations


def _safe_div(numerator: float, denominator: float, reason: str) -> dict:
    """One metric with honest undefined handling."""
    if denominator == 0:
        return {"value": None, "status": "UNDEFINED", "reason": reason}
    return {"value": float(numerator) / float(denominator), "status": "OK", "reason": None}


def binary_metrics(tp: int, tn: int, fp: int, fn: int) -> dict:
    """Binary confusion counts -> accuracy/precision/recall/specificity/F1.

    Positive class is detector-specific (e.g. META_STATEMENT).
    F1 uses the mathematically equivalent 2TP/(2TP+FP+FN) form.
    """
    for name, v in (("TP", tp), ("TN", tn), ("FP", fp), ("FN", fn)):
        if not isinstance(v, int) or v < 0:
            raise ValueError(f"{name} must be a non-negative int, got {v!r}.")
    total = tp + tn + fp + fn
    precision = _safe_div(tp, tp + fp, "No positive system predictions were produced.")
    recall = _safe_div(tp, tp + fn, "No positive human labels in the dataset.")
    f1_num = 2 * tp
    f1_den = 2 * tp + fp + fn
    if precision["value"] is None or recall["value"] is None:
        f1 = {"value": None, "status": "UNDEFINED",
              "reason": "Precision or recall is undefined."}
    elif precision["value"] + recall["value"] == 0:
        f1 = {"value": None, "status": "UNDEFINED",
              "reason": "Precision + recall is zero."}
    else:
        f1 = {"value": f1_num / f1_den, "status": "OK", "reason": None}
    return {
        "TP": tp, "TN": tn, "FP": fp, "FN": fn, "N": total,
        "accuracy": _safe_div(tp + tn, total, "Empty evaluation set (N=0)."),
        "precision": precision,
        "recall": recall,
        "specificity": _safe_div(tn, tn + fp, "No negative human labels in the dataset."),
        "f1": f1,
    }


def confusion_from_pairs(pairs: list[tuple[str, str]],
                         labels: list[str]) -> dict:
    """Multiclass matrix from (human, predicted) pairs.

    Orientation (used everywhere): rows = system prediction,
    columns = human ground truth. cells[pred][human] = {count, sample_ids}.
    """
    cells: dict[str, dict[str, dict]] = {
        p: {h: {"count": 0, "sample_ids": []} for h in labels} for p in labels
    }
    for item in pairs:
        human, predicted = item[0], item[1]
        sample_id = item[2] if len(item) > 2 else None
        if human not in labels or predicted not in labels:
            raise ValueError(
                f"Label outside schema: human={human!r} predicted={predicted!r}.")
        cells[predicted][human]["count"] += 1
        if sample_id is not None:
            cells[predicted][human]["sample_ids"].append(sample_id)
    return {"orientation": "rows=system prediction, columns=human ground truth",
            "labels": labels, "cells": cells}


def multiclass_metrics(pairs: list[tuple[str, str, str]],
                       labels: list[str]) -> dict:
    """Per-class (one-vs-rest) precision/recall/F1/support + macro/weighted.

    pairs: (human, predicted, sample_id). No global specificity: it is
    only meaningful per class one-vs-rest and reported there.
    """
    matrix = confusion_from_pairs(pairs, labels)
    cells = matrix["cells"]
    per_class = {}
    for cls in labels:
        tp = cells[cls][cls]["count"]
        fp = sum(cells[cls][h]["count"] for h in labels if h != cls)
        fn = sum(cells[p][cls]["count"] for p in labels if p != cls)
        tn = sum(cells[p][h]["count"] for p in labels for h in labels
                 if p != cls and h != cls)
        support = sum(cells[p][cls]["count"] for p in labels)
        per_class[cls] = {
            "TP": tp, "FP": fp, "FN": fn, "TN_one_vs_rest": tn,
            "support": support,
            "precision": _safe_div(tp, tp + fp,
                                   f"No system predictions of {cls}."),
            "recall": _safe_div(tp, tp + fn, f"No human labels of {cls}."),
            "f1": ({"value": None, "status": "UNDEFINED",
                    "reason": "Precision or recall is undefined."}
                   if (tp + fp == 0 or tp + fn == 0
                       or (2 * tp + fp + fn) == 0)
                   else {"value": (2 * tp) / (2 * tp + fp + fn),
                         "status": "OK", "reason": None}),
            "specificity_one_vs_rest": _safe_div(
                tn, tn + fp, f"No non-{cls} human labels."),
        }
    n = len(pairs)
    correct = sum(1 for h, p, _ in pairs if h == p)
    supports = [per_class[c]["support"] for c in labels]

    def _avg(values):
        vals = [v for v in values if v is not None]
        if not vals:
            return {"value": None, "status": "UNDEFINED",
                    "reason": "All per-class values undefined."}
        return {"value": sum(vals) / len(vals), "status": "OK", "reason": None}

    def _wavg(values):
        num = sum(v * s for v, s in zip(values, supports) if v is not None)
        den = sum(s for v, s in zip(values, supports) if v is not None)
        if den == 0:
            return {"value": None, "status": "UNDEFINED",
                    "reason": "No supported classes with defined values."}
        return {"value": num / den, "status": "OK", "reason": None}

    prec = [per_class[c]["precision"]["value"] for c in labels]
    rec = [per_class[c]["recall"]["value"] for c in labels]
    f1s = [per_class[c]["f1"]["value"] for c in labels]
    return {
        "matrix": matrix,
        "per_class": per_class,
        "N": n,
        "accuracy": _safe_div(correct, n, "Empty evaluation set (N=0)."),
        "macro_precision": _avg(prec),
        "macro_recall": _avg(rec),
        "macro_f1": _avg(f1s),
        "weighted_precision": _wavg(prec),
        "weighted_recall": _wavg(rec),
        "weighted_f1": _wavg(f1s),
    }


def cohens_kappa(labels_a: list[str], labels_b: list[str]) -> dict:
    """Cohen's kappa for two independent HUMAN raters.

    Never system-vs-human: that is detector performance, not
    inter-rater reliability. Requires >=2 shared samples.
    """
    if len(labels_a) != len(labels_b) or len(labels_a) < 2:
        return {"status": "N/A",
                "reason": "Kappa requires two raters on >=2 shared samples."}
    cats = sorted(set(labels_a) | set(labels_b))
    n = len(labels_a)
    agree = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    po = agree / n
    pe = sum(
        (sum(1 for a in labels_a if a == c) / n)
        * (sum(1 for b in labels_b if b == c) / n)
        for c in cats
    )
    if pe == 1.0:
        return {"status": "N/A",
                "reason": "Degenerate: both raters used a single label."}
    return {"status": "OK", "value": (po - pe) / (1 - pe),
            "observed_agreement": po, "expected_agreement": pe, "n": n}


def sklearn_crosscheck(pairs: list[tuple[str, str]],
                       labels: list[str]) -> dict:
    """Cross-check manual multiclass metrics against scikit-learn.

    Returns {library: {...}, manual: {...}, difference, match} so the
    library is never an unverified black box.
    """
    from services.validation import metrics as _self

    y_true = [h for h, _ in pairs]
    y_pred = [p for _, p in pairs]
    manual = _self.multiclass_metrics(
        [(h, p, f"#{i}") for i, (h, p) in enumerate(pairs)], labels)
    try:
        from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

        library = {
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "macro_precision": float(precision_score(
                y_true, y_pred, labels=labels, average="macro", zero_division=0)),
            "macro_recall": float(recall_score(
                y_true, y_pred, labels=labels, average="macro", zero_division=0)),
            "macro_f1": float(f1_score(
                y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        }
    except Exception as exc:
        return {"status": "LIBRARY_UNAVAILABLE", "reason": str(exc),
                "manual": manual}
    diffs = {}
    for key, mkey in (("accuracy", "accuracy"), ("macro_precision", "macro_precision"),
                      ("macro_recall", "macro_recall"), ("macro_f1", "macro_f1")):
        mval = manual[mkey]["value"]
        diffs[key] = None if mval is None else abs(mval - library[key])
    defined = [d for d in diffs.values() if d is not None]
    return {"status": "OK", "library": library,
            "manual": {k: manual[k] for k in
                       ("accuracy", "macro_precision", "macro_recall", "macro_f1")},
            "differences": diffs,
            "match": bool(defined) and max(defined) <= 1e-9}


def class_balance(pairs: list[tuple[str, str]]) -> dict:
    """N + counts + shares by human label, with imbalance flag."""
    counts: dict[str, int] = {}
    for human, _ in pairs:
        counts[human] = counts.get(human, 0) + 1
    n = len(pairs)
    shares = {k: (v / n if n else None) for k, v in counts.items()}
    imbalance = False
    if n and len(counts) > 1:
        imbalance = min(counts.values()) / n < 0.20
    return {"N": n, "counts": counts, "shares": shares,
            "imbalance_warning": imbalance}
