"""Media for the client presentation page (docs/model-report/trinh-bay.html): data for its interactive figures
(media/presentation.js) and MP4 clips, all computed from the app's own checkpoints and real data.

- PhysioMix: the intermediate signals of one forward pass (beat timing, harmonic pulse, network residual, motion term,
  band limit) of the shipped round-9 checkpoint (best.pt whose sha256 matches assets/neural/manifest.json).
- PhysioFlow: the sample at every Heun step from noise to waveform (shipped round-10 checkpoint, 16 steps).
- PhysioMix critic: its score for real validation windows and for generated windows (critic weights at the end of
  the round-9 training run; the checkpoint itself keeps only the generator).
- Training clips (step D, Experiment Snapshots): fixed-noise samples every 500 steps up to the step chosen by the run's
  own checkpoint_score, next to a real validation strip of the same domain (--snapshots, --windows).
- Judges (step C): copied from the judges.py result, when given.

Needs the local ml/runs folders (not in git). Report only: nothing here trains or selects a model.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import torch
from torch.nn import functional as F

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.kaggle_lsm.train_lsm import FS, LENGTH  # noqa: E402
from ml.kaggle_multidomain.data_gxu import load_input  # noqa: E402
from ml.kaggle_multidomain.experiment_v3 import conditions_for, load_best  # noqa: E402
from ml.kaggle_multidomain.labels import robust_labels  # noqa: E402
from ml.kaggle_multidomain.physio import IRR_MAX, DerivCritic  # noqa: E402

MIX_RUN = "ml/runs/physiomix9-motion-dom-result-v1/physiomix9/benchmark/L3_rel_beat_lr_crop_r1w_motion_dom_seed123"
MIX_ARM = "L3_rel_beat_lr_crop_r1w_motion_dom"
FLOW_RUN = "ml/runs/physioflow10c-final-result-v1/physioflow10/benchmark/F6_flow_flag_deriv_unif_s16_w1_seed42"
FLOW_ARM = "F6_flow_flag_deriv_unif_s16_w1"
# The round-9 run kept only the generator; step B retrained the same recipe and kept its critic (last state).
CRITIC_RUN = "ml/runs/galaxy-b-pilot-result-v1/galaxy_b/physiomix_g/L3_rel_beat_lr_crop_r1w_motion_dom_seed42"
SHOW_S = 8  # seconds drawn in the page figures
PROMPT = dict(domain="gxu_finger", bpm=72., sigma=.03)


def checked(run_dir, slot):
    manifest = json.loads((ROOT/"assets/neural/manifest.json").read_text())
    digest = hashlib.sha256((ROOT/run_dir/"best.pt").read_bytes()).hexdigest()
    if digest != manifest[slot]["checkpoint_sha256"]:
        raise ValueError(f"{run_dir} is not the app's {slot} checkpoint")
    return ROOT/run_dir


def short(y, seconds=SHOW_S, digits=3):
    y = np.asarray(y, np.float64)[:int(seconds*FS)]
    return [round(float(v), digits) for v in y]


def unit(y):
    y = np.asarray(y, np.float64)
    return (y-y.min())/max(np.ptp(y), 1e-9)


@torch.no_grad()
def physiomix_stages(model, z, condition):
    """PhysioMixR.forward with its intermediate signals kept (same operations, same order)."""
    m = model
    raw = condition[:, -3:]*m.scale+m.center
    hz = (raw[:, 0]/60).clamp(*m.hz_range)
    index, fraction, ibi = m.beats_of(z, hz, raw[:, 1].clamp(0, IRR_MAX))
    phi = 2*math.pi*(index.to(z.dtype)+fraction)
    carrier = torch.stack([phi.sin(), phi.cos(), (2*phi).sin(), (3*phi).sin()], 1)
    style = m.style(torch.cat((z[:, :8], condition), 1))
    noise = torch.cat((z[:, :m.pad].flip(1), z, z[:, LENGTH-m.pad:].flip(1)), 1) if m.pad else z
    h = torch.cat([branch(torch.cat((noise[:, None], carrier), 1)) for branch in m.branches], 1)
    for block, film in zip(m.blocks, m.film):
        gain, bias = film(style).chunk(2, 1)
        h = block(h)*(1+.1*gain[:, :, None])+.1*bias[:, :, None]
    knots = F.interpolate(m.head(F.avg_pool1d(h, FS)), size=h.shape[-1], mode="linear", align_corners=False)
    amplitude = F.softplus(knots[:, :m.k])
    shape = amplitude/amplitude.sum(1, keepdim=True).clamp_min(1e-6)
    harmonics = shape*torch.sin(m.orders*phi[:, None]+knots[:, m.k:2*m.k])
    pulse = harmonics.sum(1, keepdim=True)
    gain = torch.exp(.5*torch.tanh(knots[:, -1:]))
    beta = torch.sigmoid(m.coupling(style))
    per_beat = torch.exp(beta*torch.log(torch.cat((ibi[:, :1], ibi[:, :-1]), 1)*hz[:, None]))
    current, before = per_beat.gather(1, index), per_beat.gather(1, (index-1).clamp_min(0))
    gain = gain*(before+(current-before)*(fraction/.2).clamp(0, 1))[:, None]
    residual = .15*torch.tanh(m.out(h))
    motion = m.motion_component(style, z)
    y = gain*pulse+knots[:, 2*m.k:2*m.k+1]+residual+motion
    full = torch.fft.irfft(torch.fft.rfft(y, dim=-1)*m.band_long, n=y.shape[-1], dim=-1)[..., m.pad:m.pad+LENGTH]
    out = (full-full.amin(-1, keepdim=True))/(full.amax(-1, keepdim=True)-full.amin(-1, keepdim=True)).clamp_min(1e-6)
    reference = model(z, condition)
    if not torch.allclose(out, reference, atol=1e-5):
        raise RuntimeError("Stage replay differs from the model's forward pass")
    crop = slice(m.pad, m.pad+LENGTH)
    return dict(noise=z[0].numpy(), phase=(fraction[0, crop]).numpy(), harmonics=harmonics[0, :, crop].numpy(),
                pulse=(gain*pulse)[0, 0, crop].numpy(), residual=residual[0, 0, crop].numpy(),
                motion=motion[0, 0, crop].numpy(), summed=y[0, 0, crop].numpy(), output=out[0, 0].numpy(),
                rate_bpm=float(raw[0, 0]))


@torch.no_grad()
def flow_trajectory(model, z, condition):
    """FlowGenerator.forward (guidance 1, no finish filter) keeping x and the clean estimate at every step."""
    s = model.scaffold_of(z, condition)
    x = z[:, None]
    steps, frames = model.sample_steps, []
    for i in range(steps):
        t, t_next = 1-i/steps, 1-(i+1)/steps
        v = model.velocity(x, t, s, condition)
        frames.append(dict(t=t, x=x[0, 0].numpy().copy(), clean=(x-t*v)[0, 0].numpy().copy()))
        proposal = x+(t_next-t)*v
        x = x+(t_next-t)*.5*(v+model.velocity(proposal, t_next, s, condition)) if i < steps-1 else proposal
    out = (x-x.amin(-1, keepdim=True))/(x.amax(-1, keepdim=True)-x.amin(-1, keepdim=True)).clamp_min(1e-6)
    if not torch.allclose(out, model(z, condition), atol=1e-4):
        raise RuntimeError("Trajectory replay differs from the model's forward pass")
    frames.append(dict(t=0., x=x[0, 0].numpy(), clean=x[0, 0].numpy()))
    return frames, s[0].numpy()


def prompt_rows(conditions, domain, signal):
    """Condition rows for real windows (their own consensus rate / IBI CV / std), as the app would prompt."""
    rate, irr, _ = robust_labels(signal)
    rate = np.where(np.isfinite(rate), rate, 75.)
    irr = np.clip(np.where(np.isfinite(irr), irr, conditions.defaults[domain][0]), 0, .35)
    rows = conditions.prompt(domain, 75., .05, len(signal))
    raw = np.c_[rate, irr, signal.std(1)]
    rows[:, -3:] = (raw-conditions.center)/conditions.scale
    return rows.astype(np.float32)


@torch.no_grad()
def critic_scores(run_dir, pack, domain="gxu_finger", n=96, seed=11):
    """Generator (EMA, end of training) and critic of one PhysioMix run, on validation windows of one domain."""
    from ml.kaggle_multidomain.experiment_v3 import build, config
    state = torch.load(run_dir/"last_training_state.pt", map_location="cpu", weights_only=True)
    conditions = conditions_for(pack, "v2")
    model, critic = build(config(MIX_ARM), conditions)
    model.load_state_dict(state["ema"])
    critic.load_state_dict(state["discriminator"])
    model.eval()
    critic.eval()
    generator = model
    rng = np.random.default_rng(seed)
    ids = rng.choice(np.flatnonzero((pack["split"] == "validation") & (pack["domain"] == domain)), n, replace=False)
    real = pack["signal"][ids].astype(np.float32)
    rows = torch.tensor(prompt_rows(conditions, domain, real))
    fake = generator(torch.randn(n, LENGTH, generator=torch.Generator().manual_seed(seed)), rows)[:, 0]
    score = lambda x: critic(torch.as_tensor(x)[:, None], rows).mean(1).numpy()
    real_s, fake_s = score(real), score(fake.numpy())
    order = np.argsort(real_s)
    return dict(real=[round(float(v), 3) for v in real_s], fake=[round(float(v), 3) for v in fake_s],
                examples=dict(real_high=short(real[order[-1]]), fake_low=short(fake[int(np.argmin(fake_s))].numpy()),
                              fake_high=short(fake[int(np.argmax(fake_s))].numpy())),
                note="Step-B PhysioMix run (round-9 recipe, seed 42): EMA generator and critic at the end of training "
                     "(step 20000), validation windows of the original pack")


def snapshots(run_dirs):
    out = {}
    for name, folder in run_dirs.items():
        found = next(Path(folder).rglob("snapshots.npz"), None)
        if found is None:
            continue
        with np.load(found) as s:
            out[name] = dict(steps=s["steps"].tolist(), domains=s["domains"].tolist(), bpm=float(s["bpm"]),
                             signals=[[short(w.astype(np.float64), 10, 3) for w in frame] for frame in s["signals"]])
        history = next(Path(folder).rglob("history.json"), None)
        if history is not None:
            rows = json.loads(history.read_text())
            out[name]["curve"] = [dict(step=r["step"], S_real=round(r["S_real"], 4), C=round(r["C"], 4)) for r in rows]
    return out


def write_video(path, frames, titles, fps=4, reference=None, headers=None, labels=None):
    """frames: list of list of 1-D arrays (one panel per array). Encoded with ffmpeg (libx264, yuv420p).

    reference: optional list of fixed 1-D arrays, one per panel, drawn in a second column next to the moving one.
    headers: titles of the two columns; labels: y label per row."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import animation, pyplot as plt
    panels, columns = len(frames[0]), 2 if reference is not None else 1
    fig, axes = plt.subplots(panels, columns, figsize=(8 if columns == 1 else 9, round((1.6*panels+.9)*55)/55), dpi=110,
                             squeeze=False)  # whole-pixel even height: libx264 yuv420p needs even sizes
    lines = []
    for r, (ax, y) in enumerate(zip(axes[:, 0], frames[0])):
        t = np.arange(len(y))/FS
        (line,) = ax.plot(t, y, lw=1.4, color="#6b4fbb")
        ax.set_xlim(0, t[-1])
        ax.set_yticks([])
        ax.spines[["top", "right", "left"]].set_visible(False)
        if labels:
            ax.set_ylabel(labels[r], fontsize=9)
        lines.append(line)
    if reference is not None:
        for ax, y in zip(axes[:, 1], reference):
            ax.plot(np.arange(len(y))/FS, y, lw=1.4, color="#1d7f5f")
            ax.set_xlim(0, (len(y)-1)/FS)
            ax.set_yticks([])
            ax.spines[["top", "right", "left"]].set_visible(False)
    for c in range(columns):
        axes[-1, c].set_xlabel("giây")
        if headers:
            axes[0, c].set_title(headers[c], fontsize=9)
    title = fig.suptitle(titles[0], fontsize=10, linespacing=1.4)

    def update(i):
        for ax, line, y in zip(axes[:, 0], lines, frames[i]):
            line.set_ydata(y)
            lo, hi = float(np.min(y)), float(np.max(y))
            ax.set_ylim(lo-.05*(hi-lo+1e-9), hi+.05*(hi-lo+1e-9))
        title.set_text(titles[i])
        return lines
    fig.tight_layout()
    writer = animation.FFMpegWriter(fps=fps, codec="libx264", extra_args=["-pix_fmt", "yuv420p", "-crf", "28"])
    animation.FuncAnimation(fig, update, frames=len(frames), blit=False).save(str(path), writer=writer)
    plt.close(fig)


def selected_step(folder):
    """Step the run itself keeps: lowest checkpoint_score in history.json, which must match training_result.json."""
    folder = Path(folder)
    history = json.loads(next(folder.rglob("history.json")).read_text())
    best = min(history, key=lambda r: r["checkpoint_score"])["step"]
    recorded = json.loads(next(folder.rglob("training_result.json")).read_text())["best_step"]
    if best != recorded:
        raise ValueError(f"{folder}: history.json picks step {best}, training_result.json says {recorded}")
    return best


def real_strips(windows_path, domains, seconds=SHOW_S):
    """One real validation window per domain: the first one by index (fixed rule, not picked for looks).
    Rows with split == external or test are never used. Each is min-max scaled like the generators' output."""
    with np.load(windows_path) as w:
        strips, notes = [], []
        for domain in domains:
            index = np.flatnonzero((w["split"] == "validation") & (w["domain"] == domain))
            if not len(index):
                raise ValueError(f"no validation windows for domain {domain}")
            i = int(index[0])
            if not np.isfinite(w["signal"][i]).all():
                raise ValueError(f"validation window {i} of {domain} has non-finite samples")
            strips.append(unit(w["signal"][i])[:int(seconds*FS)])
            notes.append(f"{domain}: {w['subject'][i]}, cửa sổ {i}")
    return strips, notes


def train_clip(path, name, run_dir, windows_path, source_note, tail_steps=(5000, 10000, 15000, 20000), hold=12):
    """Training clip up to the selected step (+ a short, labelled tail), generated panels next to real validation strips.
    Rows whose domain has no real window in windows.npz (wrist_daily, GalaxyPPG) are left out."""
    with np.load(next(Path(run_dir).rglob("snapshots.npz"))) as s:
        steps, domains, signals, bpm = s["steps"].tolist(), s["domains"].tolist(), s["signals"], float(s["bpm"])
    keep = [i for i, d in enumerate(domains) if d in ("gxu_finger", "wrist")]
    strips, notes = real_strips(windows_path, [domains[i] for i in keep])
    best = selected_step(run_dir)
    if best not in steps:
        raise ValueError(f"{run_dir}: no snapshot at the selected step {best}")
    shown = [t for t in steps if t <= best] + [t for t in tail_steps if t > best and t in steps]
    frames, titles = [], []
    head = f"{name}: bản thử nghiệm bước D ({source_note}), KHÔNG phải model trong app"
    for t in shown:
        frame = [unit(signals[steps.index(t), i].astype(np.float64))[:SHOW_S*FS] for i in keep]
        if t < best:
            note = f"bước train {t}"
        elif t == best:
            note = f"bước train {t} = BƯỚC ĐƯỢC CHỌN (checkpoint_score thấp nhất)"
        else:
            note = f"bước train {t}: sau bước được chọn, KHÔNG dùng"
        repeat = hold if t == best else 1
        frames += [frame]*repeat
        titles += [f"{head}\n{note} · lệnh {bpm:g} nhịp/phút"]*repeat
    write_video(path, frames, titles, fps=6, reference=strips,
                headers=["mô hình sinh (nhiễu cố định)", "sóng thật: người validation, một đoạn minh hoạ"],
                labels=[domains[i] for i in keep])
    return dict(best_step=best, last_step=shown[-1], domains=[domains[i] for i in keep], real=notes)


def stages_figure(path, mix):
    """Static overview of the PhysioMix forward pass (the same signals as the page's stepper)."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    panels = [("1. Nhiễu z (đầu vào ngẫu nhiên)", [mix["noise"]]), ("2. Nhịp tim dựng từ lệnh (pha trong nhịp)", [mix["phase"]]),
              ("3. Sáu sóng sin hài do mạng chọn", mix["harmonics"]), ("4. Ghép thành nhịp mạch", [mix["pulse"]]),
              ("5. Chi tiết mạng TCN thêm vào (±0,15)", [mix["residual"]]), ("6. Tổng (+ chuyển động)", [mix["summed"]]),
              ("7. Lọc 0,5–8 Hz, chuẩn hoá: sóng ra DAC", [mix["output"]])]
    fig, axes = plt.subplots(len(panels), 1, figsize=(9, 11), dpi=120, sharex=True)
    for ax, (title, ys) in zip(axes, panels):
        for y in ys:
            ax.plot(np.arange(len(y))/FS, y, lw=1.2 if len(ys) > 1 else 1.5)
        ax.set_title(title, loc="left", fontsize=10)
        ax.set_yticks([])
        ax.spines[["top", "right", "left"]].set_visible(False)
    axes[-1].set_xlabel("giây")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="ml/runs/halovie-datasets-v1")
    parser.add_argument("--critic-data", default="ml/runs/halovie-datasets-v2")
    parser.add_argument("--output", default="docs/model-report/media")
    parser.add_argument("--snapshots", action="append", default=[], help="name=run folder holding snapshots.npz")
    parser.add_argument("--windows", default="ml/runs/physio3-data-v1/physio3_data/windows.npz",
                        help="real windows for the training clips (validation split only)")
    parser.add_argument("--clips-only", action="store_true", help="only write train-<name>.mp4 from --snapshots")
    parser.add_argument("--source-note", default="galaxy-d-pilot, seed 42", help="run label written on every clip frame")
    parser.add_argument("--judges", help="judges.py result JSON (step C)")
    parser.add_argument("--daily", help="Step D result folder(s), comma separated")
    a = parser.parse_args(argv)
    torch.set_num_threads(4)
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    runs = dict(x.split("=", 1) for x in a.snapshots)
    if a.clips_only:
        for name, folder in runs.items():
            print(name, train_clip(out/f"train-{name}.mp4", name, ROOT/folder, ROOT/a.windows, a.source_note))
        return
    pack, _ = load_input(ROOT/a.data, "ppg_physiomix_v3")
    development = {k: v[np.isin(pack["split"], ["train", "validation"])] for k, v in pack.items()}
    conditions = conditions_for(development, "v2")
    v3g, _ = load_input(ROOT/a.critic_data, "ppg_physiomix_v3g")
    critic_pack = {k: v[np.isin(v3g["split"], ["train", "validation"])] for k, v in v3g.items()}
    prompt = torch.tensor(conditions.prompt(PROMPT["domain"], PROMPT["bpm"], PROMPT["sigma"], 1))
    z = torch.randn(1, LENGTH, generator=torch.Generator().manual_seed(2026))
    mix, _ = load_best(MIX_ARM, checked(MIX_RUN, "physiomix"), conditions, None, "cpu")
    flow, _ = load_best(FLOW_ARM, checked(FLOW_RUN, "physioflow"), conditions, None, "cpu")
    stages = physiomix_stages(mix, z, prompt)
    trajectory, scaffold = flow_trajectory(flow, z, prompt)
    real = pack["signal"][np.flatnonzero((pack["split"] == "validation") & (pack["domain"] == PROMPT["domain"]))[3]]
    data = dict(prompt=PROMPT, fs=FS, show_s=SHOW_S, real_example=short(real),
                physiomix=dict(noise=short(stages["noise"]), phase=short(stages["phase"]),
                               harmonics=[short(h) for h in stages["harmonics"]], pulse=short(stages["pulse"]),
                               residual=short(stages["residual"]), motion=short(stages["motion"]),
                               summed=short(stages["summed"]), output=short(stages["output"])),
                physioflow=dict(scaffold=[short(c) for c in scaffold],
                                frames=[dict(t=round(f["t"], 4), x=short(f["x"]), clean=short(unit(f["clean"])))
                                        for f in trajectory]),
                critic=critic_scores(ROOT/CRITIC_RUN, critic_pack))
    data["snapshots"] = snapshots(runs)
    if a.judges:
        data["judges"] = json.loads(Path(a.judges).read_text())
    (out/"presentation.js").write_text("// Generated by scripts/build_presentation_media.py; do not edit by hand.\n"
                                       "window.PRES = "+json.dumps(data, separators=(",", ":"))+";\n")
    stages_figure(out/"physiomix-7-buoc.png", data["physiomix"])
    write_video(out/"physioflow-tu-nhieu-thanh-song.mp4",
                [[f["x"][:SHOW_S*FS], unit(f["clean"])[:SHOW_S*FS]] for f in trajectory],
                [f"PhysioFlow: bước {i}/{len(trajectory)-1}, t = {f['t']:.2f} (trên: mẫu hiện tại, dưới: dự đoán sóng sạch)"
                 for i, f in enumerate(trajectory)], fps=3)
    for name, folder in runs.items():
        train_clip(out/f"train-{name}.mp4", name, ROOT/folder, ROOT/a.windows, a.source_note)
    print("wrote", sorted(p.name for p in out.iterdir()))


if __name__ == "__main__":
    main()
