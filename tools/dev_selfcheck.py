"""Self-check on the DEV split only, against labels made by eye (reports/dev_labels.csv).

The student repo has no ground truth, so this is how the group checks itself (docs/HUONG_DAN: "tự gắn nhãn vài mẫu").
It never touches fixtures/*/gt/ and never looks at split == eval.

    python -m tools.dev_selfcheck out/baseline/ranked_review.csv out/poc/ranked_review.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

LABELS = Path(__file__).resolve().parents[1] / "reports" / "dev_labels.csv"


def check(pred_path: str, budget: int = 20) -> dict:
    lab = pd.read_csv(LABELS)
    pred = pd.read_csv(pred_path)
    pred = pred[pred.image_id.isin(lab.image_id)].sort_values("score", ascending=False, kind="mergesort")
    pos = set(lab.loc[lab.is_defect == 1, "image_id"])
    top = pred.head(budget)
    hit = top.image_id.isin(pos)
    # average precision over the whole ranking (budget-free)
    hits = pred.image_id.isin(pos).tolist()
    ap, tp = 0.0, 0
    for i, h in enumerate(hits, 1):
        if h:
            tp += 1
            ap += tp / i
    neg_top = top.loc[~hit, ["image_id"]].merge(lab, on="image_id")
    by_type = lab[lab.is_defect == 1].assign(found=lambda d: d.image_id.isin(top.image_id)).groupby("defect_type").found.agg(["sum", "count"])
    return {
        "n_dev": len(lab), "n_defects": len(pos), "B": budget,
        "recall@B": hit.sum() / len(pos), "precision@B": hit.mean(), "AP": ap / len(pos),
        "max_recall@B": min(budget, len(pos)) / len(pos),
        "false_alarms": neg_top[["image_id", "camera_id", "light"]].values.tolist(),
        "by_type_found": {k: f"{int(r['sum'])}/{int(r['count'])}" for k, r in by_type.iterrows()},
    }


if __name__ == "__main__":
    for p in sys.argv[1:] or ["out/poc/ranked_review.csv"]:
        print(p)
        for k, v in check(p).items():
            print(f"  {k}: {v}")
