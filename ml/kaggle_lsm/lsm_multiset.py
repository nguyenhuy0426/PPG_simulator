"""LSM-GAN (author topology) trained on every public set available to us, then benchmarked across them.

Ding et al. (arXiv 2108.05272v2) trained on fingertip PPG from 126 UCLA in-hospital patients with AF/non-AF labels;
those data are private. They tested on DeepBeat and a MIMIC-III AF set (annotations by Bashar et al.). Here the
author topology and released objective (train_lsm: make_networks, BCE + all-pairs log-spectral matching) are trained on
  bidmc         BIDMC 1.0.0, frozen 32/7/7 people of LSM-GAN v2 (bidmc_split.json), no rhythm labels
  mimic_af      MIMIC PERform AF (Charlton, Zenodo 6807403, ODbL 1.0; AF labels from Bashar et al.), AF people
  mimic_non_af  its non-AF people
DeepBeat (wrist, 25 s at 32 Hz, Synapse login) is not included. Preprocessing follows the paper: 40 Hz, 0.9-5 Hz FIR,
non-overlapping 30 s, min-max per window; AF and non-AF are trained separately, as in the paper.

Two recipes, because one paper epoch is only a few steps on these small sets:
  paper  batch 200, Adam lr 1e-3 lowered by 1e-4 per epoch (floor 1e-4, ours), at most 100 epochs, early stop after
         6 epochs without a validation gain
  steps  released script: Adam 5e-4, betas (.5, .999), batch 200, 3000 steps, best validation checkpoint
Validation people pick checkpoints; test people are scored once. Benchmark: fidelity on each set's test people and
across sets (ACF MMD2, log-PSD MMD2, log-PSD RMSE) next to a real training-window replay; and the paper's use, AF
detection on MIMIC PERform test people by a small 1D CNN trained on real, real + synthetic and synthetic-only windows.
The CNN is not the paper's ResNet-50 and the test sets are a few people: results are exploratory.

    Build (laptop):  lsm_multiset build --bidmc dataset/bidmc/bidmc_data.mat --mimic ~/datasets/mimic_perform \
                         --output ml/runs/lsm-multiset-data-v1
    Run (Kaggle):    lsm_multiset run --pack /kaggle/input --output /kaggle/working/lsm_multi
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.io import loadmat
from scipy.signal import resample_poly
from scipy.spatial.distance import pdist
import torch
from torch import nn

from ml.kaggle_lsm.train_lsm import (FS, LENGTH, MAT_HASH, VARIANTS, bandpass, features, make_networks, normalize,
                                     prepare_discriminator_for_generator, save_json, score, spectral_loss)

PROTOCOL = "ppg_lsm_multiset_v1"
SETS = ("bidmc", "mimic_af", "mimic_non_af")
MIMIC_FILES = {"mimic_af": ("mimic_perform_af_data.mat", "38adc07e4420226a0edfe9769a23284f"),
               "mimic_non_af": ("mimic_perform_non_af_data.mat", "d1c4f93442a3b4c9cb95718ca0a57013")}  # Zenodo md5
MIMIC_SPLIT_SEED = 2108
ARMS = ("lsm_repo_corrected", "dcgan1200_no_spectral")
RECIPES = dict(paper=dict(batch=200, lr=1e-3, lr_drop=1e-4, lr_floor=1e-4, max_epochs=100, patience=6),
               steps=dict(batch=200, lr=5e-4, steps=3000, every=100))
SEEDS = (42, 123, 2026)
CLASSIFIER = dict(epochs=30, batch=64, lr=1e-3, seeds=(0, 1, 2))


def md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def windows(wave, native_fs):
    """Paper preprocessing of one recording -> (n, LENGTH) float32 windows and the count of rejected windows."""
    if native_fs != 125:
        raise ValueError("Expected 125 Hz source")
    wave = np.asarray(wave, np.float64).ravel()
    out, rejected = [], 0
    filtered = bandpass(resample_poly(np.nan_to_num(wave), 8, 25))
    for left in range(0, len(filtered)-LENGTH+1, LENGTH):
        try:
            # Gaps are judged on the native samples the window covers (a resampled mask has edge ripple).
            if not np.isfinite(wave[left*25//8:-(-(left+LENGTH)*25//8)]).all():
                raise ValueError("gap")
            out.append(normalize(filtered[left:left+LENGTH]))
        except ValueError:
            rejected += 1
    return out, rejected


def split_people(people, seed=MIMIC_SPLIT_SEED, share=.15):
    people = sorted(set(people))
    order = [people[i] for i in np.random.default_rng(seed).permutation(len(people))]
    held = max(2, round(share*len(people)))
    return {"validation": order[:held], "test": order[held:2*held], "train": order[2*held:]}


def build(bidmc, mimic, output):
    bidmc, mimic, output = Path(bidmc), Path(mimic).expanduser(), Path(output)
    if hashlib.sha256(bidmc.read_bytes()).hexdigest() != MAT_HASH:
        raise ValueError("BIDMC checksum mismatch")
    rows, groups, rejected = [], {}, {}
    frozen = json.loads((Path(__file__).parents[1]/"kaggle_multidomain"/"bidmc_split.json").read_text())
    groups["bidmc"] = {k: frozen[k] for k in ("train", "validation", "test")}
    rejected["bidmc"] = 0
    for rec in loadmat(bidmc, simplify_cells=True)["data"]:
        w, bad = windows(rec["ppg"]["v"], float(rec["ppg"]["fs"]))
        rejected["bidmc"] += bad
        rows += [("bidmc", str(rec["fix"]["id"]), x) for x in w]
    for name, (file, digest) in MIMIC_FILES.items():
        if md5(mimic/file) != digest:
            raise ValueError(f"{file} checksum mismatch")
        data = loadmat(mimic/file, simplify_cells=True)["data"]
        if {int(r["fix"]["af_status"]) for r in data} != {int(name == "mimic_af")}:
            raise ValueError(f"{file}: AF status does not match the file")
        rejected[name] = 0
        for rec in data:
            w, bad = windows(rec["ppg"]["v"], float(rec["ppg"]["fs"]))
            rejected[name] += bad
            rows += [(name, str(rec["fix"]["subj_id"]), x) for x in w]
        groups[name] = split_people([r[1] for r in rows if r[0] == name])
    sets = np.array([r[0] for r in rows]); people = np.array([r[1] for r in rows])
    split = np.array([next(k for k, v in groups[s].items() if p in v) for s, p in zip(sets, people)])
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output/"windows.npz", signal=np.stack([r[2] for r in rows]), set=sets, subject=people,
                        split=split)
    counts = {s: {k: dict(windows=int(((sets == s) & (split == k)).sum()), people=len(groups[s][k]))
                  for k in ("train", "validation", "test")} for s in SETS}
    save_json(output/"manifest.json", dict(
        protocol=PROTOCOL, windows_sha256=hashlib.sha256((output/"windows.npz").read_bytes()).hexdigest(),
        fs_hz=FS, length=LENGTH, groups=groups, counts=counts, rejected_windows=rejected,
        preprocessing="125 Hz -> resample_poly 8/25 -> 161-tap zero-phase FIR 0.9-5 Hz -> 30 s -> min-max",
        sources=dict(bidmc="BIDMC 1.0.0, Pimentel et al., ODC-By 1.0",
                     mimic="MIMIC PERform AF/non-AF, Charlton, Zenodo 6807403, ODbL 1.0; MIMIC-III Waveform; "
                           "AF annotations Bashar et al., CC BY 4.0"),
        limitations=["Not the paper's private UCLA training set", "DeepBeat not included",
                     "MIMIC PERform: 19 AF and 16 non-AF people, 20 min each"]))
    return counts


def load(root):
    paths = [p for p in Path(root).rglob("windows.npz") if (p.parent/"manifest.json").exists()
             and json.loads((p.parent/"manifest.json").read_text()).get("protocol") == PROTOCOL]
    if len(paths) != 1:
        raise ValueError(f"Expected one {PROTOCOL} pack, found {len(paths)}")
    manifest = json.loads((paths[0].parent/"manifest.json").read_text())
    if hashlib.sha256(paths[0].read_bytes()).hexdigest() != manifest["windows_sha256"]:
        raise ValueError(f"{PROTOCOL} checksum mismatch")
    with np.load(paths[0], allow_pickle=False) as f:
        return {k: f[k] for k in f.files}, manifest


def part(pack, name, split):
    return pack["signal"][(pack["set"] == name) & (pack["split"] == split)]


def bandwidths(x):
    return [max(float(np.median(pdist(f, "sqeuclidean"))), 1e-6) for f in features(x)]


def generate(g, n, seed, device):
    z = torch.tensor(np.random.default_rng(seed).standard_normal((n, LENGTH)).astype(np.float32))
    g.eval()
    with torch.no_grad():
        return torch.cat([g(b.to(device)) for b in z.split(200)]).cpu().numpy()[:, 0]


def train_gan(train, valid, arm, recipe, seed, device, log=print):
    """One generator; returns (generator in eval mode on CPU, history, best validation row)."""
    loss_kind, pairing, w_match, w_self = VARIANTS[arm]
    r = RECIPES[recipe]
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    g, d = make_networks(); g.to(device); d.to(device)
    lr = r["lr"]
    optg = torch.optim.Adam(g.parameters(), lr=lr, betas=(.5, .999))
    optd = torch.optim.Adam(d.parameters(), lr=lr, betas=(.5, .999))
    criterion = nn.BCELoss() if loss_kind == "bce" else nn.MSELoss()
    x = torch.tensor(train[:, None], device=device)
    batch = min(r["batch"], len(x))
    widths = bandwidths(train)
    history, best, best_state, step = [], None, None, 0

    def update(real):
        fake = g(torch.randn(len(real), LENGTH, device=device))
        optd.zero_grad(set_to_none=True)
        pr, pf = d(real), d(fake.detach())
        ld = criterion(pr, torch.ones_like(pr))+criterion(pf, torch.zeros_like(pf))
        ld.backward(); optd.step()
        prepare_discriminator_for_generator(d)
        optg.zero_grad(set_to_none=True)
        pred = d(fake)
        lg = criterion(pred, torch.ones_like(pred))
        if w_match or w_self:
            matching, consistency = spectral_loss(fake, real, pairing=pairing)
            lg = lg+w_match*matching+w_self*consistency
        lg.backward(); optg.step()
        for p in d.parameters():
            p.requires_grad_(True)
        if not torch.isfinite(ld+lg):
            raise RuntimeError(f"Nonfinite loss at step {step}")
        return float(ld), float(lg)

    def check(epoch=None):
        nonlocal best, best_state
        val = score(generate(g, len(valid), seed+7, device), valid, widths)
        row = dict(step=step, epoch=epoch, lr=lr, d_loss=losses[0], g_loss=losses[1], validation=val,
                   selection=val["acf_mmd2"]+val["log_psd_mmd2"])
        history.append(row)
        g.train(); d.train()
        if best is None or row["selection"] < best["selection"]:
            best, best_state = row, {k: v.detach().cpu().clone() for k, v in g.state_dict().items()}
            return True
        return False

    g.train(); d.train()
    if recipe == "paper":
        wait = 0
        for epoch in range(r["max_epochs"]):
            lr = max(r["lr"]-r["lr_drop"]*epoch, r["lr_floor"])
            for opt in (optg, optd):
                for group in opt.param_groups:
                    group["lr"] = lr
            for idx in torch.tensor(rng.permutation(len(x)), device=device).split(batch):
                if len(idx) < 2:
                    continue
                step += 1
                losses = update(x[idx])
            wait = 0 if check(epoch) else wait+1
            if wait >= r["patience"]:
                break
    else:
        for step in range(1, r["steps"]+1):
            losses = update(x[torch.tensor(rng.integers(0, len(x), batch), device=device)])
            if step % r["every"] == 0 or step == r["steps"]:
                check()
    g.load_state_dict(best_state)
    log(json.dumps(dict(arm=arm, recipe=recipe, seed=seed, steps=step, best_step=best["step"],
                        best_selection=best["selection"])))
    return g.cpu().eval(), history, best


class Detector(nn.Module):
    """Small 1D CNN AF detector (not the paper's ResNet-50)."""
    def __init__(self):
        super().__init__()
        layers, previous = [], 1
        for width in (16, 32, 64, 64):
            layers += [nn.Conv1d(previous, width, 7, stride=2, padding=3), nn.BatchNorm1d(width), nn.ReLU()]
            previous = width
        self.body = nn.Sequential(*layers, nn.AdaptiveAvgPool1d(1), nn.Flatten())
        self.head = nn.Linear(previous, 1)

    def forward(self, x):
        return self.head(self.body(x[:, None])).squeeze(-1)


def auc(y, s):
    order = np.argsort(s)
    ranks = np.empty(len(s)); ranks[order] = np.arange(1, len(s)+1)
    pos = y == 1
    return float((ranks[pos].sum()-pos.sum()*(pos.sum()+1)/2)/max(pos.sum()*(~pos).sum(), 1))


def detect(train_x, train_y, valid_x, valid_y, test_x, test_y, seed, device):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    net = Detector().to(device)
    opt = torch.optim.Adam(net.parameters(), lr=CLASSIFIER["lr"])
    loss = nn.BCEWithLogitsLoss(pos_weight=torch.tensor((train_y == 0).sum()/max((train_y == 1).sum(), 1),
                                                         device=device, dtype=torch.float32))
    tx, ty = torch.tensor(train_x, device=device), torch.tensor(train_y, dtype=torch.float32, device=device)

    def scores(x):
        net.eval()
        with torch.no_grad():
            return torch.cat([torch.sigmoid(net(torch.tensor(b, device=device))) for b in np.array_split(x, max(1, len(x)//256))]).cpu().numpy()

    best, state = -1., None
    for _ in range(CLASSIFIER["epochs"]):
        net.train()
        for idx in torch.tensor(rng.permutation(len(tx)), device=device).split(CLASSIFIER["batch"]):
            if len(idx) < 2:
                continue
            opt.zero_grad(set_to_none=True)
            loss(net(tx[idx]), ty[idx]).backward()
            opt.step()
        a = auc(valid_y, scores(valid_x))
        if a > best:
            best, state = a, {k: v.detach().clone() for k, v in net.state_dict().items()}
    net.load_state_dict(state)
    s = scores(test_x)
    pred = s >= .5
    tp, fp, fn = int((pred & (test_y == 1)).sum()), int((pred & (test_y == 0)).sum()), int((~pred & (test_y == 1)).sum())
    return dict(validation_auc=best, test_auc=auc(test_y, s), test_f1=2*tp/max(2*tp+fp+fn, 1),
                test_accuracy=float((pred == (test_y == 1)).mean()))


def run(pack_root, output, device, smoke=False):
    pack, manifest = load(pack_root)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    seeds = SEEDS[:1] if smoke else SEEDS
    recipes = {k: dict(v) for k, v in RECIPES.items()}
    if smoke:
        recipes["paper"]["max_epochs"], recipes["steps"]["steps"], recipes["steps"]["every"] = 2, 20, 10
        CLASSIFIER["epochs"] = 2
    RECIPES.update(recipes)
    save_json(output/"configuration.json", dict(protocol=PROTOCOL, windows_sha256=manifest["windows_sha256"],
                                                counts=manifest["counts"], arms=ARMS, recipes=RECIPES, seeds=seeds,
                                                classifier=CLASSIFIER, smoke=smoke, device=str(device),
                                                gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None))
    test = {s: part(pack, s, "test") for s in SETS}
    widths = {s: bandwidths(part(pack, s, "train")) for s in SETS}
    fidelity, generators, started = [], {}, time.monotonic()
    for name in SETS:
        train, valid = part(pack, name, "train"), part(pack, name, "validation")
        for arm in ARMS:
            for recipe in RECIPES:
                for seed in seeds:
                    g, history, best = train_gan(train, valid, arm, recipe, seed, device,
                                                 log=lambda m: print(name, m, flush=True))
                    tag = f"{name}/{arm}/{recipe}/seed{seed}"
                    folder = output/tag; folder.mkdir(parents=True)
                    save_json(folder/"history.json", history)
                    traced = torch.jit.trace(g, torch.randn(1, LENGTH))
                    traced.save(str(folder/"generator_cpu.ts"))
                    generators[tag] = g
                    for target in SETS:
                        row = dict(train_set=name, arm=arm, recipe=recipe, seed=seed, test_set=target,
                                   best_step=best["step"], validation_selection=best["selection"],
                                   **score(generate(g.to(device), len(test[target]), seed+1000, device), test[target],
                                           widths[target]))
                        g.cpu(); fidelity.append(row)
                    save_json(output/"fidelity.json", fidelity)
    for target in SETS:
        for source in SETS:
            replay = part(pack, source, "train")
            idx = np.random.default_rng(99).choice(len(replay), len(test[target]), replace=True)
            fidelity.append(dict(train_set=source, arm="real_train_replay", recipe="-", seed=99, test_set=target,
                                 **score(replay[idx], test[target], widths[target])))
    save_json(output/"fidelity.json", fidelity)
    # Paper's use: AF detection on MIMIC PERform test people. Recipe per arm chosen on validation, not test.
    def mean_selection(arm, recipe, name):
        return np.mean([r["validation_selection"] for r in fidelity if r.get("arm") == arm and r["recipe"] == recipe
                        and r["train_set"] == name and r["test_set"] == name])
    chosen = {arm: min(RECIPES, key=lambda rc: mean_selection(arm, rc, "mimic_af")+mean_selection(arm, rc, "mimic_non_af"))
              for arm in ARMS}
    xs = {(c, k): part(pack, c, k) for c in ("mimic_af", "mimic_non_af") for k in ("train", "validation", "test")}
    label = lambda k: (np.concatenate([xs["mimic_af", k], xs["mimic_non_af", k]]),
                       np.r_[np.ones(len(xs["mimic_af", k])), np.zeros(len(xs["mimic_non_af", k]))])
    (rx, ry), (vx, vy), (tx, ty) = label("train"), label("validation"), label("test")
    detection = []
    for cs in CLASSIFIER["seeds"]:
        detection.append(dict(condition="real", seed=cs, **detect(rx, ry, vx, vy, tx, ty, cs, device)))
        for arm in ARMS:
            for seed in seeds:
                synth = {c: generate(generators[f"{c}/{arm}/{chosen[arm]}/seed{seed}"].to(device),
                                     len(xs[c, "train"]), seed+2000+cs, device) for c in ("mimic_af", "mimic_non_af")}
                for g in generators.values():
                    g.cpu()
                sx = np.concatenate([synth["mimic_af"], synth["mimic_non_af"]])
                sy = np.r_[np.ones(len(synth["mimic_af"])), np.zeros(len(synth["mimic_non_af"]))]
                for condition, (x, y) in (("real+synthetic", (np.concatenate([rx, sx]), np.r_[ry, sy])),
                                          ("synthetic_only", (sx, sy))):
                    detection.append(dict(condition=condition, arm=arm, recipe=chosen[arm], gan_seed=seed, seed=cs,
                                          **detect(x.astype(np.float32), y, vx, vy, tx, ty, cs, device)))
        save_json(output/"detection.json", detection)
    summary = summarize(fidelity, detection, chosen, seeds)
    save_json(output/"summary.json", dict(summary, seconds=time.monotonic()-started,
                                          scope="exploratory; test people few; DeepBeat absent; not the paper's data"))
    print("COMPLETE "+json.dumps(summary)[:4000], flush=True)
    return summary


def summarize(fidelity, detection, chosen, seeds):
    table = {}
    for r in fidelity:
        key = f"{r['train_set']}->{r['test_set']}|{r['arm']}|{r['recipe']}"
        table.setdefault(key, []).append(r)
    agg = lambda rows, k: dict(mean=float(np.mean([r[k] for r in rows])), sd=float(np.std([r[k] for r in rows])),
                               n=len(rows))
    fid = {k: {m: agg(v, m) for m in ("acf_mmd2", "log_psd_mmd2", "mean_log_psd_rmse", "dominant_bpm_median")}
           for k, v in table.items()}
    groups = {}
    for r in detection:
        groups.setdefault(f"{r['condition']}|{r.get('arm', '-')}", []).append(r)
    det = {k: {m: agg(v, m) for m in ("test_auc", "test_f1", "test_accuracy")} for k, v in groups.items()}
    return dict(fidelity=fid, detection=det, detection_recipe=chosen, gan_seeds=list(seeds))


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build"); b.add_argument("--bidmc", required=True); b.add_argument("--mimic", required=True)
    b.add_argument("--output", required=True)
    r = sub.add_parser("run"); r.add_argument("--pack", required=True); r.add_argument("--output", required=True)
    r.add_argument("--smoke", action="store_true")
    r.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    a = p.parse_args(argv)
    if a.command == "build":
        print(json.dumps(build(a.bidmc, a.mimic, a.output), indent=1))
    else:
        if Path("/kaggle/working").is_dir() and a.device == "cpu" and not a.smoke:
            raise RuntimeError("GPU required on Kaggle; refusing silent CPU fallback")
        run(a.pack, a.output, torch.device(a.device), a.smoke)


if __name__ == "__main__":
    main()
