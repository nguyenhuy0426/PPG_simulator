"""Export the R1c rhythm models (per-dataset AR on log intervals) for the app: assets/neural/rhythm_r1c.json.

Fitted on the training windows of the v4 pack with the same code that RULE_RHYTHM and RULE_RHYTHM_2 judged
(rhythm.fit_models on flow.window_peaks intervals). The app reads only this JSON (core/rhythm_range.py).

    PPG_DRY_RUN=1 .venv/bin/python -m ml.kaggle_multidomain.rhythm_export --pack ml/runs/physioflow2-data-v4 \
        --decision ml/runs/rhythm-v1/rhythm_eval_rule2.json --output assets/neural/rhythm_r1c.json
"""
import argparse
import json
from pathlib import Path

from ml.kaggle_lsm.train_lsm import save_json
from ml.kaggle_multidomain.data_dual import load_dual
from ml.kaggle_multidomain.flow import window_peaks
from ml.kaggle_multidomain.rhythm import BEATS, DURATION, P_MAX, SIGMA_RANGE, Z95, fit_models
from ml.kaggle_multidomain.rhythm_eval import real_sequences


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", required=True)
    parser.add_argument("--decision", required=True, help="rhythm_eval output of RULE_RHYTHM_2")
    parser.add_argument("--output", required=True)
    a = parser.parse_args(argv)
    decision = json.loads(Path(a.decision).read_text())
    if decision.get("decision") != "R1" or decision.get("split") != "test":
        raise SystemExit("RULE_RHYTHM_2 did not select R1c; nothing to export")
    pack, manifest = load_dual(a.pack)
    train = real_sequences(pack, "train")
    models = fit_models([pack["signal"][i] for d in train for i, _ in train[d]], [d for d in train for _ in train[d]],
                        window_peaks)
    save_json(Path(a.output), dict(
        model="R1c: per-dataset AR(p) on standardised log inter-beat intervals, re-centred over the window's beats",
        rule=decision["rule"], outcome=dict(overall=decision["overall"], mean_rate_abs_error_bpm=decision["mae"]
                                            if "mae" in decision else decision["mean_rate_abs_error_bpm"],
                                            guard=decision["guard"]),
        pack_windows_sha256=manifest["windows_sha256"], beats=BEATS, duration_s=DURATION, p_max=P_MAX, z95=Z95,
        sigma_range=list(SIGMA_RANGE),
        domains={d: dict(coef=[float(c) for c in m.coef], innovation_sd=float(m.innovation_sd),
                         training_windows=len(train[d])) for d, m in sorted(models.items())},
        scope="Engineering model of rate variability from PPG peak intervals; not a clinical HRV or arrhythmia model"))
    print(a.output)


if __name__ == "__main__":
    main()
