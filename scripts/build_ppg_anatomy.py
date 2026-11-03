"""Data for the feature and learning figures of docs/model-report/trinh-bay.html (media/ppg-anatomy.js), computed with the
judge's own feature code, so the page draws what the score measures. Sources, none of them selected by score:
- anatomy: real validation windows of the local pack and the first APFT-GAN evaluation windows; from each set the regular
  window with the clearest dicrotic rebound, since the figure has to show it (an illustration, not a random sample).
- learning: training histories and fixed-noise snapshots of the runs behind the training videos and the app's models.
- copy check and coverage: docs/paper/evidence/realism-v1/realism_round10.json.

Needs the local ml/runs folder (not in git) and the generated windows of the APFT-GAN kernel. Report only.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from scipy.signal import find_peaks

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.kaggle_lsm.train_lsm import FS, LENGTH  # noqa: E402
from ml.kaggle_physigpt import judge_physigpt as jp  # noqa: E402

OUT = ROOT/"docs/model-report/media/ppg-anatomy.js"
REALISM = ROOT/"docs/paper/evidence/realism-v1/realism_round10.json"
GAN_RUN = ROOT/"docs/physigpt/evidence/ppg-physigpt-apft-gan-v1"
EVAL_START = jp.SIZES["fit"]+jp.SIZES["inner"]
CANDIDATES = 256
MAX_IBI_CV, MIN_TEMPLATE_CORR = .08, .9
PACK = "physio3-data-v1/physio3_data/windows.npz"
REAL_DOMAIN = "perform_large"  # MIMIC-III, the source APFT-GAN learned from; validation people only
SHOW_S = 10
ACF_S = 3
DOMAINS = dict(gxu_finger="Ngón tay", perform_large="ICU lớn", bidmc="BIDMC", perform_af="Rung nhĩ",
               perform_non_af="Không rung nhĩ", wrist="Cổ tay vận động")
VIDEO_MIX = "galaxy-d-pilot-result-v1/daily_d/physiomix_d_seed42/L3_rel_beat_lr_crop_r1w_motion_dom_seed42"
VIDEO_FLOW = "galaxy-d-pilot-result-v1/daily_d/physioflow_d_seed42/F10_flow_unif_stop01_seed42"
APP_MIX = "physiomix9-motion-dom-result-v1/physiomix9/benchmark/L3_rel_beat_lr_crop_r1w_motion_dom_seed123"
APP_FLOW = "physioflow10c-final-result-v1/physioflow10/benchmark/F6_flow_flag_deriv_unif_s16_w1_seed42"
PEAK_PROMINENCE = .6  # of the window's SD; only counts the beats a reader sees in the video frames


def rounded(y, digits=4):
    return [round(float(v), digits) for v in y]


def template_marks(template, seconds):
    """Where the judge's rise, width and notch fall on the median beat, in seconds from the foot."""
    t = np.linspace(0, seconds, len(template))
    top = int(np.argmax(template))

    def at(level, step):
        return float(np.interp(jp.crossing(template, top, level, step), np.arange(len(template)), t))
    fall = template[top:]
    low = np.minimum.accumulate(fall)
    rebound = fall-low
    marks = dict(top=float(t[top]), t10=at(.1, -1), t90=at(.9, -1), w_lo=at(.5, -1), w_hi=at(.5, 1), notch=None)
    if rebound.max() > .01:
        crest = int(np.argmax(rebound))
        notch = int(np.argmin(fall[:crest+1]))
        marks.update(notch=float(t[top+notch]), notch_y=float(fall[notch]), crest=float(t[top+crest]),
                     crest_y=float(fall[crest]))
    return marks


def anatomy(x):
    x = np.asarray(x, np.float64)
    beats = jp.beats_of(x)
    features = {k: float(v[0]) for k, v in jp.signal_features(x[None]).items()}
    features.update({k: float(v) for k, v in jp.window_beats(x).items()})
    shapes = np.array([np.interp(np.linspace(0, b-a, jp.BEAT_POINTS), np.arange(b-a+1), y) for a, b, _, _, y in beats])
    template = np.median(shapes, 0)
    seconds = float(np.median([(b-a)/FS for a, b, *_ in beats]))
    n = SHOW_S*FS
    d = x-x.mean()
    acf = np.fft.irfft(np.abs(np.fft.rfft(d, 2*LENGTH))**2)[:ACF_S*FS+1]
    freq = np.fft.rfftfreq(LENGTH, 1/FS)
    power = np.abs(np.fft.rfft(d))**2
    return dict(wave=rounded(x[:n]), feet=[int(a) for a, *_ in beats if a < n],
                peaks=[int(a+top) for a, _, top, *_ in beats if a+top < n], shapes=[rounded(s, 3) for s in shapes[:16]],
                template=rounded(template, 3), beat_s=seconds, marks=template_marks(template, seconds),
                diff=rounded(np.diff(x[:n])*FS, 2), hist=rounded(np.histogram(x, 24, (0, 1), density=True)[0], 3),
                acf=rounded(acf/acf[0], 3),
                spectrum=rounded(power[freq <= 10]/power[1:].max(), 4), spectrum_df=float(freq[1]), features=features)


def clearest(windows):
    """The regular window with the clearest dicrotic rebound: the anatomy of a beat is what the figure has to show."""
    def value(w):
        f = jp.window_beats(w)
        regular = f["beat_coverage"] > .8 and f["ibi_cv"] < MAX_IBI_CV and f["template_corr"] > MIN_TEMPLATE_CORR
        return f["dicrotic_rebound"] if regular else -1.
    scores = [value(w) for w in windows]
    if max(scores) <= 0:
        raise ValueError("no regular window with a dicrotic rebound among the candidates")
    return np.asarray(windows[int(np.argmax(scores))], np.float64)


def peaks_per_minute(x):
    z = (x-x.mean())/x.std()
    return len(find_peaks(np.convolve(z, np.ones(3)/3, "same"), distance=int(.3*FS), prominence=PEAK_PROMINENCE)[0])/(len(x)/FS)*60


def history(folder):
    rows = json.loads((folder/"history.json").read_text())
    best = min(rows, key=lambda r: r["checkpoint_score"])
    return dict(steps=[r["step"] for r in rows], score=rounded([r["checkpoint_score"] for r in rows]),
                C=rounded([r["C"] for r in rows]), S=rounded([r["S_real"] for r in rows]), best=best["step"])


def snapshots(folder, chosen, domain="wrist"):
    with np.load(folder/"snapshots.npz") as s:
        steps, domains, signals, bpm = s["steps"].tolist(), s["domains"].tolist(), s["signals"], float(s["bpm"])
    row = signals[:, domains.index(domain)].astype(np.float64)
    keep = [steps.index(chosen), len(steps)-1]
    return dict(command_bpm=bpm, domain=domain, steps=steps, peaks=rounded([peaks_per_minute(w) for w in row], 1),
                frames=[dict(step=steps[i], wave=rounded(((row[i]-row[i].min())/np.ptp(row[i]))[:SHOW_S*FS], 3))
                        for i in keep])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(ROOT/"ml/runs"), help="the local ml/runs folder")
    parser.add_argument("--generated", required=True, help="generated.npy of the APFT-GAN sampling kernel")
    args = parser.parse_args()
    runs = Path(args.runs)
    with np.load(runs/PACK) as pack:
        rows = np.flatnonzero((pack["split"] == "validation") & (pack["domain"] == REAL_DOMAIN))[:CANDIDATES]
        real = pack["signal"][rows].astype(np.float64)
    real = (real-real.min(1, keepdims=True))/np.ptp(real, axis=1, keepdims=True)
    generated = np.load(args.generated, mmap_mode="r")[EVAL_START:EVAL_START+CANDIDATES].astype(np.float64)
    gan = [json.loads(line) for line in (GAN_RUN/"metrics.jsonl").read_text().splitlines()]
    gan = [r for r in gan if "select" in r]
    realism = json.loads(REALISM.read_text())
    sources = ("real_unseen", "round9", "physioflow")
    copies = {DOMAINS[d]: {k: {m: round(realism["memorization"][d][k][m], 4) for m in ("median", "p95", "above_0_99")}
                           for k in sources} for d in DOMAINS}
    cover = {DOMAINS[d]: {k: round(realism["realism"][d][k]["coverage"], 3)
                          for k in ("real_other_people", "round9", "physioflow")} for d in DOMAINS}
    mix = history(runs/VIDEO_MIX)
    data = dict(fs=FS, show_s=SHOW_S, anatomy=dict(real=anatomy(clearest(real)), ai=anatomy(clearest(generated))),
                learning=dict(mix=mix, flow=history(runs/VIDEO_FLOW), app_mix=history(runs/APP_MIX),
                              app_flow=history(runs/APP_FLOW), wrist=snapshots(runs/VIDEO_MIX, mix["best"]),
                              gan=dict(steps=[r["step"] for r in gan],
                                       mean=rounded([r["select"]["mean_similarity"] for r in gan]),
                                       acf=rounded([r["select"]["similarity"]["acf_peak"] for r in gan]))),
                copies=copies, coverage=cover)
    OUT.write_text("// Generated by scripts/build_ppg_anatomy.py; do not edit by hand.\nwindow.ANATOMY = "
                   + json.dumps(data, ensure_ascii=False, separators=(",", ":"))+";\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size//1024} KB)")
    for name in data["anatomy"]:
        a = data["anatomy"][name]
        print(name, a["beat_s"], a["marks"], {k: round(v, 3) for k, v in a["features"].items()})


if __name__ == "__main__":
    main()
