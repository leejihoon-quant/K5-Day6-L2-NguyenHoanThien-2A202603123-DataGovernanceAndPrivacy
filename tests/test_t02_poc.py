"""PoC T02: each defect detector fires on its synthetic defect and stays quiet on a clean image,
and decide() maps the flagged fraction to GO / REWORK / HOLD. No fixtures or ground truth needed."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter

from src.pipeline import FLAG_AT, decide, defect_scores, image_features


def _clean_scene() -> np.ndarray:
    rng = np.random.default_rng(42)
    g = np.full((180, 320), 120.0)
    for x0 in range(0, 320, 40):                       # sharp, high-contrast blocks (buildings, road marks)
        g[60:180, x0:x0 + 20] = rng.integers(60, 200)
    g[:60] = 170
    return np.stack([g, g, g], axis=-1).clip(0, 255).astype(np.uint8)


def _scores(img: np.ndarray) -> dict:
    return defect_scores(image_features(img))


def test_detectors_and_decision_policy():
    clean = _clean_scene()
    assert max(_scores(clean).values()) < FLAG_AT

    blurred = gaussian_filter(clean.astype(float), sigma=(6, 6, 0)).astype(np.uint8)
    assert _scores(blurred)["blur"] >= FLAG_AT

    dark = (clean * 0.2).astype(np.uint8)
    assert _scores(dark)["dark"] >= FLAG_AT

    glare = clean.copy()
    glare[40:100, 120:200] = 255                       # one large saturated blob = local glare
    assert _scores(glare)["glare"] >= FLAG_AT

    def run_decide(n_flagged: int, n: int = 40):
        action = ["RECAPTURE"] * n_flagged + ["KEEP"] * (n - n_flagged)
        final = pd.DataFrame({"pred_action": action, "pred_defect_type": ["blur"] * n, "split": ["eval"] * n})
        ctx = SimpleNamespace(param=lambda k, d=None: d, config={"owner": "test-owner"}, track="t02",
                              out=lambda name: name)
        return decide(ctx, final)

    assert run_decide(0).canonical == "GO"
    assert run_decide(5).canonical == "REWORK"
    d = run_decide(20)
    assert d.canonical == "HOLD" and d.reason_code == "SYSTEMIC_CAPTURE_DEFECTS" and d.owner == "test-owner"
