"""YOUR PoC PIPELINE — T02 Raw QC Triage (blur / dark / glare / compression).

Lab contract = 5 automated steps, run by `python -m src.main ...`:
    01 load      input + provenance check (manifest.csv)
    02 process   4 complementary defect detectors -> one suspicion score per image
    03 rank      top-B (B=20) of the eval pool -> review_queue.csv + contact_sheet.html
    04 review    human-in-the-loop: queue -> reviewer decisions -> overrides + audit log
    05 decide    GO / HOLD / REWORK for the batch + KEEP / RECAPTURE per image, with reason_code + owner

Required output: out/ranked_review.csv (image_id, score [+ pred_defect_type, pred_action]). Evaluate with
    python -m src.evaluate --track t02 --pred out/poc/ranked_review.csv

Rules: never read fixtures/*/gt/ here (the GT guard will stop you); seed everything via ctx.rng;
no network calls; fail loudly on missing models instead of downloading.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import ndimage as ndi

from .common.contact_sheet import render_contact_sheet
from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.image_ops import laplacian_variance, load_rgb, to_gray
from .common.manifest import verify_manifest
from .common.review import load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track

# ---------------------------------------------------------------------------------------------
# PoC: 4 complementary defect detectors, each normalised so that 0.5 == its frozen threshold,
# then max-combined into one suspicion score.
#
# ALL thresholds below were frozen from the *dev* split only (images labelled by eye in
# reports/dev_labels.csv; the student repo has no GT). Nothing was tuned on split == eval.
# ---------------------------------------------------------------------------------------------
T_BLUR = 0.03         # contrast-normalised Laplacian: dev blur <= 0.0052, dev clean >= 0.157 (cam_B = soft optics)
T_DARK = 118.0        # 99.5th-percentile luminance: dev dark <= 89, dev clean (even night) >= 148
T_GLARE = 180.0       # largest connected blob of pixels >= 235: dev glare >= 404 px, dev clean <= 78 px
T_BLOCK = 1.65        # JPEG blockiness (8px-border gradient minus interior gradient): dev compression >= 1.92, clean <= 1.38
SHARP_K = 4.0         # steepness of the r^k / (1 + r^k) squashing
FLAG_AT = 0.5         # score >= 0.5 -> a detector fired -> RECAPTURE
HOLD_FRACTION = 0.40  # decide(): if >= 40% of the batch is flagged, suspect the capture chain -> HOLD

DEFECTS = ("blur", "dark", "glare", "compression")


def _squash(r: float) -> float:
    """r = value / threshold (>1 means 'worse than threshold'). Maps to (0,1) with 0.5 at r=1."""
    r = max(float(r), 1e-9) ** SHARP_K
    return r / (1.0 + r)


def blockiness(g: np.ndarray, block: int = 8) -> float:
    """Mean |gradient| across 8px block borders minus mean |gradient| inside blocks (JPEG blocking)."""
    dx, dy = np.abs(np.diff(g, axis=1)), np.abs(np.diff(g, axis=0))
    bx, ix = dx[:, block - 1::block].mean(), np.delete(dx, np.s_[block - 1::block], axis=1).mean()
    by, iy = dy[block - 1::block, :].mean(), np.delete(dy, np.s_[block - 1::block], axis=0).mean()
    return float((bx + by) / 2 - (ix + iy) / 2)


def image_features(img: np.ndarray) -> dict:
    g = to_gray(img)
    # contrast-normalised sharpness: cam_B soft optics and dim-but-sharp images are not blur
    lap_norm = laplacian_variance(img) / (float(g.std()) ** 2 + 1.0)
    lab, n = ndi.label(g >= 235)
    glare_blob = int(np.bincount(lab.ravel())[1:].max()) if n else 0     # LOCAL glare, not a global mean
    return {
        "lap_norm": lap_norm,
        "p995": float(np.percentile(g, 99.5)),     # night scenes keep bright lights; a gain-dimmed day scene does not
        "glare_blob": glare_blob,
        "blockiness": blockiness(g),
        "mean": float(g.mean()),
    }


def defect_scores(f: dict) -> dict:
    return {
        "blur": _squash(T_BLUR / max(f["lap_norm"], 1e-9)),
        "dark": _squash(T_DARK / max(f["p995"], 1e-9)),
        "glare": _squash(f["glare_blob"] / T_GLARE),
        "compression": _squash(max(f["blockiness"], 0.0) / T_BLOCK),
    }


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    if ctx.track != "t02":
        raise NotImplementedError(f"src/pipeline.py implements only t02 (got {ctx.track})")
    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")
    data = {"manifest": pd.read_csv(manifest) if manifest.exists() else None}
    data["images"] = pd.read_csv(ctx.input_dir / "images.csv")
    return data


# ---------------------------------------------------------------- 02 process
def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    rows = []
    for r in data["images"].itertuples(index=False):
        f = image_features(load_rgb(ctx.input_dir / r.path))
        s = defect_scores(f)
        top = max(s, key=s.get)
        # max = "any detector fired"; the tiny sum term only breaks ties between equally-bad images.
        score = max(s.values()) + 0.01 * sum(s.values())
        flagged = max(s.values()) >= FLAG_AT
        rows.append({
            "image_id": r.image_id, "score": round(score, 6),
            "pred_defect_type": top if flagged else "none",
            "pred_action": "RECAPTURE" if flagged else "KEEP",
            "reason": f"{top}={s[top]:.2f}" if flagged else "no_detector_fired",
            "camera_id": r.camera_id, "light": r.light, "split": r.split, "path": r.path,
            **{f"s_{k}": round(v, 4) for k, v in s.items()},
            **{k: round(v, 4) for k, v in f.items()},
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 03 rank
def _pool(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    """Review pool = the split we must triage (default eval); dev only exists to freeze thresholds."""
    sp = ctx.param("review_split", "eval")
    pool = scored[scored["split"] == sp] if sp else scored
    return pool if len(pool) else scored


def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    budget = int(ctx.param("budget", 20))
    q = make_review_queue(_pool(ctx, scored), id_col="image_id", score_col="score", budget=budget,
                          reason_col="reason", action_col="pred_action", slice_col="light", evidence_col="path")
    write_review_queue(q, ctx.out("review_queue.csv"))
    render_contact_sheet(q, ctx.out("contact_sheet.html"), image_root=ctx.input_dir, title="t02 Raw QC — PoC review queue")
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """Apply out/review_queue_reviewed.csv if present (otherwise pass-through).

    Semantics for T02 (every change is audit-logged with who / when / why):
      approve / skip / escalate -> keep the machine decision (escalate is only logged)
      reject                    -> reviewer says the image is fine: KEEP, score 0
      edit + override_value     -> KEEP | RECAPTURE | one of blur/dark/glare/compression
    """
    reviewed_path = ctx.output_dir / "review_queue_reviewed.csv"
    scored = scored.copy()
    if not reviewed_path.exists():
        return scored
    reviewed = load_review_decisions(reviewed_path)
    ctx.stats["n_reviewed"] = len(reviewed)
    for r in reviewed.itertuples(index=False):
        m = scored["image_id"] == r.item_id
        if not m.any():
            continue
        i = scored.index[m][0]
        before = {"pred_action": scored.at[i, "pred_action"], "pred_defect_type": scored.at[i, "pred_defect_type"]}
        ov = str(r.override_value).strip().lower()
        if r.reviewer_decision == "reject" or (r.reviewer_decision == "edit" and ov == "keep"):
            scored.loc[i, ["pred_action", "pred_defect_type", "score"]] = ["KEEP", "none", 0.0]
        elif r.reviewer_decision == "edit" and ov in ("recapture", *DEFECTS):
            scored.at[i, "pred_action"] = "RECAPTURE"
            if ov in DEFECTS:
                scored.at[i, "pred_defect_type"] = ov
            scored.at[i, "score"] = max(float(scored.at[i, "score"]), 2.0)   # human-confirmed defect goes first
        after = {"pred_action": scored.at[i, "pred_action"], "pred_defect_type": scored.at[i, "pred_defect_type"]}
        ctx.audit.log(actor=r.reviewer, action=f"review:{r.reviewer_decision}", item_id=str(r.item_id),
                      before=before, after=after, reason=r.review_note, reviewed_at=r.reviewed_at)
    return scored


# ---------------------------------------------------------------- 05 decide
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    pool = _pool(ctx, final)
    n, flagged = len(pool), int((pool.pred_action == "RECAPTURE").sum())
    frac = flagged / max(n, 1)
    by_type = pool[pool.pred_action == "RECAPTURE"].pred_defect_type.value_counts().to_dict()
    owner = ctx.config.get("owner", "TODO-owner")
    ev = [str(ctx.out("ranked_review.csv")), str(ctx.out("review_queue.csv"))]
    metrics = {"n_images": n, "n_recapture": flagged, "recapture_fraction": round(frac, 3), "by_type": by_type}
    if flagged == 0:
        return Decision("GO", "ALL_KEEP", f"0/{n} images flagged: batch accepted", owner, ctx.track, ev, metrics)
    if frac >= HOLD_FRACTION:
        return Decision("HOLD", "SYSTEMIC_CAPTURE_DEFECTS",
                        f"{flagged}/{n} images flagged ({frac:.0%} >= {HOLD_FRACTION:.0%}): suspect the capture chain, "
                        f"do not release the batch; by type {by_type}", owner, ctx.track, ev, metrics)
    return Decision("REWORK", "RECAPTURE_FLAGGED_IMAGES",
                    f"{flagged}/{n} images flagged: RECAPTURE only those, KEEP the rest; by type {by_type}",
                    owner, ctx.track, ev, metrics)


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    final = final.sort_values("score", ascending=False, kind="mergesort")
    final[spec.pred_columns + [c for c in final.columns if c not in spec.pred_columns]].to_csv(ctx.out(spec.pred_file), index=False)
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
