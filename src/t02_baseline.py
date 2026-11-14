"""T02 baseline: ONE global Laplacian-variance threshold (blur only), no normalisation.

Required by docs/tracks/T02.md section 4. Same pool, same budget, same seed as the PoC.
It only sees blur: dark / glare / compression images get a *low* suspicion score
(they are often sharp, or even sharper than clean images because of blocking artifacts),
and soft-optics cam_B images are false alarms.

    python -m src.main --track t02 --pipeline src.t02_baseline --output out/baseline_lap --run-name baseline_lap --offline --seed 42
"""
from __future__ import annotations

import pandas as pd

from .common.context import RunContext
from .common.contact_sheet import render_contact_sheet
from .common.decision import Decision, write_decision
from .common.image_ops import laplacian_variance, load_rgb
from .common.review import make_review_queue, write_review_queue
from .metrics.tracks import get_track

# Frozen from the dev split (visually-labelled blur images have lap < 10, clean ones > 150).
LAP_THRESHOLD = 100.0


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    if ctx.track != "t02":
        raise NotImplementedError("t02_baseline only implements t02")
    items = pd.read_csv(ctx.input_dir / "images.csv")
    lap = [laplacian_variance(load_rgb(ctx.input_dir / p)) for p in items.path]
    items = items.assign(lap_var=lap)
    items["score"] = 1.0 / (items.lap_var + 1e-6)          # blurrier -> higher
    items["reason"] = ["low_sharpness" if v < LAP_THRESHOLD else "sharp" for v in items.lap_var]
    ctx.stats["n_items"] = len(items)
    budget = int(ctx.param("budget", 20))
    pool = items[items.split == ctx.param("review_split", "eval")]
    q = make_review_queue(pool, "image_id", "score", budget, reason_col="reason", evidence_col="path")
    write_review_queue(q, ctx.out("review_queue.csv"))
    render_contact_sheet(q, ctx.out("contact_sheet.html"), image_root=ctx.input_dir, title="t02 Laplacian baseline queue")
    items.sort_values("score", ascending=False)[["image_id", "score", "lap_var", "reason"]].to_csv(ctx.out(spec.pred_file), index=False)
    write_decision(Decision(status="HOLD", reason_code="BASELINE_ONLY", reason="Laplacian-only baseline: blur only, never release on this",
                            owner=ctx.config.get("owner", "baseline"), scope=ctx.track, evidence=[str(ctx.out(spec.pred_file))]),
                   ctx.out("decision.json"), ctx.out("decision_log.csv"))
