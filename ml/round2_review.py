"""Blinded human waveform review; pending labels cannot be used for training."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from ml.kaggle_arch.train_architectures import load_prepared, PREPARED_SHA256


def build_pack(prepared, output, per_class_train=80, per_class_validation=40):
    x, c, masks = load_prepared(prepared)
    data = np.load(prepared, allow_pickle=False)
    rng = np.random.default_rng(28092026)
    cases = []
    for split, count in (("train", per_class_train), ("validation", per_class_validation)):
        for flag in (0, 1):
            ids = np.flatnonzero(masks[split] & (c[:, -1] == flag))
            groups = [rng.permutation(ids[data["subject"][ids] == subject]).tolist()
                      for subject in np.unique(data["subject"][ids])]
            chosen = []
            while len(chosen) < min(count, len(ids)):
                for group in groups:
                    if group and len(chosen) < count:
                        chosen.append(group.pop())
            for index in chosen:
                cases.append(dict(id=int(index), split=split, subject=str(data["subject"][index]),
                                  record=int(data["record"][index]), start_sample=int(data["start_sample"][index]),
                                  hr=float(c[index, 0]*200), waveform=x[index].tolist(),
                                  decision="pending", notch="", sp=None, dn=None, dp=None, notes=""))
    rng.shuffle(cases)
    payload = dict(schema=1, prepared_sha256=PREPARED_SHA256, reviewer="", reviewed_at="", cases=cases,
                   note="Blinded to original detector labels; train/validation only; NOT independent test")
    output.mkdir(parents=True, exist_ok=False)
    (output / "review-template.json").write_text(json.dumps(payload, indent=2) + "\n")
    template = Path(__file__).with_name("round2_review.html").read_text()
    (output / "review.html").write_text(template.replace("__REVIEW_DATA__", json.dumps(payload)))
    print(f"Prepared {len(cases)} unreviewed cases in {output}; no manual labels invented")
    return payload


def curated_data(prepared, annotations, min_train=32, min_validation=16):
    x, c, masks = load_prepared(prepared)
    data = np.load(prepared, allow_pickle=False)
    raw = Path(annotations).read_bytes()
    review = json.loads(raw)
    if review.get("schema") != 1 or review.get("prepared_sha256") != PREPARED_SHA256:
        raise ValueError("Review schema or source checksum mismatch")
    if not str(review.get("reviewer", "")).strip() or not str(review.get("reviewed_at", "")).strip():
        raise ValueError("Human reviewer and review timestamp required; pending labels cannot train")
    ids, conditions, splits, seen = [], [], [], set()
    counts = dict(pending=0, uncertain=0, reject=0, accept=0)
    for row in review["cases"]:
        index = row["id"]
        if type(index) is not int or not 0 <= index < len(x) or index in seen:
            raise ValueError("Invalid or duplicate source index")
        seen.add(index)
        split = row["split"]
        if split not in ("train", "validation") or not masks[split][index]:
            raise ValueError("Test rows or inconsistent split are forbidden")
        if row["subject"] != str(data["subject"][index]):
            raise ValueError("Subject provenance mismatch")
        decision = row["decision"]
        if decision not in counts:
            raise ValueError("Unknown review decision")
        counts[decision] += 1
        if decision != "accept":
            continue
        sp = row.get("sp")
        if type(sp) not in (int, float) or not np.isfinite(sp) or not 0 < sp < 1:
            raise ValueError("Accepted pulse needs a finite manually marked SP")
        notch = row.get("notch")
        if notch not in ("present", "absent"):
            raise ValueError("Accepted pulse needs an explicit notch decision")
        condition = np.array([c[index, 0], sp, 0, 0, 0, 0, 0], dtype=np.float32)
        if notch == "present":
            dn, dp = row.get("dn"), row.get("dp")
            if any(type(v) not in (int, float) or not np.isfinite(v) for v in (dn, dp)) or not sp < dn < dp < 1:
                raise ValueError("Require manually marked SP < DN < DP")
            condition[2:] = [dn, dp, np.interp(dn, np.linspace(0, 1, 256), x[index]),
                             np.interp(dp, np.linspace(0, 1, 256), x[index]), 1]
        ids.append(index); conditions.append(condition); splits.append(split)
    ids = np.asarray(ids, dtype=int)
    conditions = np.asarray(conditions, dtype=np.float32).reshape(-1, 7)
    result_masks = {s: np.asarray([v == s for v in splits], dtype=bool) for s in ("train", "validation")}
    for split, minimum in (("train", min_train), ("validation", min_validation)):
        mask = result_masks[split]
        if mask.sum() < minimum or any(np.sum(conditions[mask, -1] == flag) < minimum//4 for flag in (0, 1)):
            raise ValueError(f"Need >= {minimum} accepted {split} cases, including >= {minimum//4} per notch class")
    provenance = dict(review_sha256=hashlib.sha256(raw).hexdigest(), reviewer=review["reviewer"],
                      reviewed_at=review["reviewed_at"], counts=counts, source_indices=ids.tolist(),
                      prepared_sha256=PREPARED_SHA256,
                      note="Human-reviewed development data; external unseen cohort still required")
    return x[ids], conditions, result_masks, data["subject"][ids], provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=Path("ml/runs/kaggle-v1/ppg_run/prepared.npz"))
    parser.add_argument("--output", type=Path, default=Path("ml/runs/round2-review"))
    parser.add_argument("--annotations", type=Path)
    args = parser.parse_args()
    if args.annotations:
        *_, provenance = curated_data(args.prepared, args.annotations)
        print(json.dumps(provenance, indent=2))
    else:
        build_pack(args.prepared, args.output)
