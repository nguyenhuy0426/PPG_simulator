"""Package PPG-physiGPT kernels (same payload format as ml/kaggle_multidomain/stage_kernel.py).

data shard k (CPU, internet): mimic_wdb over the record range [start, stop) -> /kaggle/working/shard
train stage k (T4 x2): train.py on the mounted shards (and solo outputs, --solos) after smoke runs that measure
eager against torch.compile; stage 0 trains on all of them as new data, stage k > 0 mounts stage k-1's output and
starts from its stable.pt, with the earlier shards as replay. Kaggle mounts a kernel's output at
/kaggle/input/notebooks/<owner>/<slug> (seen in solotrain 0); the script also accepts /kaggle/input/<slug>.
tpu stage k (TPU v3-8): train_tpu.py, the same stage as train k on the Kaggle TPU, after a smoke run on synthetic
windows that also logs the torch/torch_xla versions of the TPU image.
solo k (T4 x2, internet): one kernel that needs no finished data kernel: a GPU smoke run on synthetic windows, then
mimic_wdb for --hours into /kaggle/working/shard, then stage 0 of train.py on that shard for the rest of the kernel
budget. Its shard mounts later like any data shard (Windows finds it by manifest.json).
gan (T4 x2): gan.py (APFT-GAN) on the mounted shards, fine-tuning the release.pt of --from-slug (the V1 large decay
kernel) against a critic, after a smoke run of the tiny config on synthetic windows on the same GPUs.
judge (T4 x2): ml.kaggle_physigpt.judge_physigpt on the mounted shards and a finished stage's release.pt: the model
judge and its features on GPU 0, the null and damaged-real control judges on GPU 1, as separate processes.
sample (T4 x2): generator windows only, from a checkpoint in a dataset, without real data, for an account that
cannot mount the shards; judge --generated-slug --cpu then scores them on the account that can (no GPU quota).
solotrain k (T4 x2): stage 0 again on solo k's shard (its output mounted), after smoke runs that measure eager
against torch.compile on the same GPUs; planned for many epochs and ended by --plateau, since solo's own 4-epoch
plan over a small shard is a few hundred steps.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zlib

OWNER = "charlesday2612"
COMMON = ["ml/kaggle_lsm/train_lsm.py", "ml/kaggle_physigpt/mimic_wdb.py"]
SOURCES = {"data": COMMON+["ml/kaggle_multidomain/data.py", "ml/kaggle_multidomain/view.py"],
           "train": COMMON+["ml/kaggle_physigpt/model.py", "ml/kaggle_physigpt/train.py"]}
SOURCES["solo"] = SOURCES["data"]+SOURCES["train"][len(COMMON):]
SOURCES["tpu"] = SOURCES["train"]+["ml/kaggle_physigpt/train_tpu.py"]
SOURCES["solotrain"] = SOURCES["train"]
SOURCES["decay"] = SOURCES["train"]
SOURCES["judge"] = SOURCES["train"]+["ml/kaggle_physigpt/judge_physigpt.py", "ml/kaggle_multidomain/strict_judge.py",
                                      "ml/kaggle_multidomain/physio.py", "ml/kaggle_multidomain/view.py",
                                      "ml/kaggle_multidomain/models.py", "ml/kaggle_multidomain/labels.py",
                                      "ml/kaggle_multidomain/data.py", "ml/kaggle_multidomain/benchmark.py",
                                      "ml/kaggle_multidomain/control.py"]
SOURCES["sample"] = SOURCES["judge"]
# APFT-GAN: the judge's modules (signal features, StrictCritic) plus PhysioGAN-R's loss and augmentation
SOURCES["gan"] = SOURCES["judge"]+["ml/kaggle_multidomain/physiogan_r.py", "ml/kaggle_multidomain/data_r.py",
                                   "ml/kaggle_physigpt/gan.py"]
# RSR-FlowGAN (ml/kaggle_multidomain/rsr_flowgan.py) on the v3 pack and the app bundle: its module-level imports
SOURCES["rsrgan"] = ["ml/kaggle_lsm/train_lsm.py", "ml/kaggle_physigpt/mimic_wdb.py", "ml/kaggle_physigpt/model.py",
                     "ml/kaggle_physigpt/train.py", "ml/kaggle_physigpt/judge_physigpt.py",
                     *(f"ml/kaggle_multidomain/{m}.py" for m in ("benchmark", "control", "data", "data_gxu", "data_more",
                                                                  "data_r", "flow", "labels", "models", "physio",
                                                                  "physiogan_r", "rsr_flowgan", "strict_judge", "train",
                                                                  "view"))]
SOURCES["rsrfid"] = SOURCES["rsrgan"]   # the app's generators on the feature tier, no training
RSR_DATASETS = ("ppg-physio3-data-v1", "ppg-app-models-v1")
RSR_JUDGE_HOURS = 1.3   # after training: three sources' sets, the feature tier and 8 strict-judge fits on two T4s
TPU_HOURS = 8.3     # Kaggle's TPU session limit is taken as 9 h (not confirmed from a document)
KERNEL_HOURS = 11.5   # Kaggle stops a GPU kernel at 12 h; the rest is train.py's own reserve plus packing


def shard_slug(k):
    return f"ppg-physigpt-mimic3-shard{k}-v1"


def decay_slug(k):
    return f"ppg-physigpt-decay{k}-v1"


def stage_slug(k):
    return f"ppg-physigpt-stage{k}-v1"


def solo_slug(k):
    return f"ppg-physigpt-solo{k}-v1"


def tpu_slug(k):
    return f"ppg-physigpt-tpu-stage{k}-v1"


def solotrain_slug(k):
    return f"ppg-physigpt-solo{k}-train-v1"


def mount_lookup(owner):
    """Run-time lookup of a mounted kernel output or dataset, failing before any GPU time is spent. Kaggle mounts a
    kernel output under notebooks/<owner>/<slug>; the dataset path is not documented, so the owner level of
    /kaggle/input is searched two levels deep as well."""
    return ("def mounted(slug):\n"
            "    root = pathlib.Path('/kaggle/input')\n"
            "    for path in (root/slug, pathlib.Path('/kaggle/input/notebooks/{owner}')/slug,\n"
            "                 pathlib.Path('/kaggle/input/datasets/{owner}')/slug,\n"
            "                 *root.glob('*/'+slug), *root.glob('*/*/'+slug)):\n"
            "        if path.is_dir():\n            return str(path)\n"
            "    raise FileNotFoundError(f'{slug} is not mounted under /kaggle/input')\n").replace("{owner}", owner)


def entry_for(kind, shard=0, start=0, stop=10**9, cap=300, target=5_000_000, hours=10.5, stage=0, shards=(0,),
              config="base", epochs=4., extra=(), smoke_only=False, solos=(), datasets=(), owner=OWNER,
              kernel_hours=KERNEL_HOURS, checkpoint="release.pt", judge_seeds=3, decay_steps=0, from_slug=None,
              gen_steps=32, skip_controls=False, no_clamp=False, hold_steps=0, tag="", generated_slug=None, cpu=False):
    if kind == "data":
        args = ["--output", "/kaggle/working/shard", "--start", str(start), "--stop", str(stop), "--cap", str(cap),
                "--target", str(target), "--hours", str(hours)]
        return f"from ml.kaggle_physigpt.mimic_wdb import main\nmain({args!r})"
    if kind == "solo":
        if hours > KERNEL_HOURS-2:
            raise ValueError(f"solo: --hours {hours} of data leaves under 2 h of the {KERNEL_HOURS} h kernel to train")
        data = ["--output", "/kaggle/working/shard", "--start", str(start), "--stop", str(stop), "--cap", str(cap),
                "--target", str(target), "--hours", str(hours)]
        train = ["--data", "/kaggle/working/shard", "--output", "/kaggle/working/stage0", "--config", config,
                 "--epochs", str(epochs), *extra]
        return ("import time\nfrom ml.kaggle_physigpt.mimic_wdb import main as build\n"
                "from ml.kaggle_physigpt.train import main as train, smoke\nbegin = time.time()\n"
                f"print('smoke', json.dumps(smoke('/tmp/physigpt_smoke', {config!r})), flush=True)\n"
                f"build({data!r})\n"
                f"left = {KERNEL_HOURS} - (time.time()-begin)/3600\n"
                f"train({train!r} + ['--hours', f'{{left:.3f}}'])")
    if kind == "solotrain":
        # The mounted solo output holds shard/ (with manifest.json) and its short stage0/ (none), so the input
        # root finds exactly its shard wherever Kaggle mounts it.
        train = ["--data", "/kaggle/input", "--output", "/kaggle/working/stage0", "--config", config,
                 "--epochs", str(epochs), *extra]
        return ("import time\nfrom ml.kaggle_physigpt.train import main as train, pick_compile\nbegin = time.time()\n"
                f"use, report = pick_compile('/tmp/physigpt_smoke', {config!r})\n"
                "print('smoke', json.dumps(report), flush=True)\n"
                f"left = {KERNEL_HOURS} - (time.time()-begin)/3600\n"
                f"train({train!r} + (['--compile'] if use else []) + ['--hours', f'{{left:.3f}}'])")
    if kind == "rsrfid":
        return ("from ml.kaggle_multidomain.rsr_flowgan import main as rsr\n"
                "rsr(['--input-root', '/kaggle/input', '--output', '/kaggle/working/fidelity', '--fidelity-only'])")
    if kind == "rsrgan":
        smoke = ["--input-root", "/kaggle/input", "--output", "/tmp/rsr_smoke", "--steps", "3", "--batch", "4",
                 "--anchor", "4", "--critic-warmup", "1", "--eval-every", "2", "--rt-gate", "-1", "--skip-judge"]
        return ("import time\nfrom ml.kaggle_multidomain.rsr_flowgan import main as rsr\nbegin = time.time()\n"
                f"rsr({smoke!r})\nprint('smoke done', flush=True)\n"
                f"left = {kernel_hours} - {RSR_JUDGE_HOURS} - (time.time()-begin)/3600\n"
                "rsr(['--input-root', '/kaggle/input', '--output', '/kaggle/working/rsr_flowgan', "
                f"*{list(extra)!r}, '--hours', f'{{left:.3f}}'])")
    if kind == "gan":
        if not from_slug:
            raise ValueError("gan: --from-slug names the kernel whose release.pt is fine-tuned")
        slugs = [shard_slug(k) for k in shards]+[solo_slug(k) for k in solos]+list(datasets)
        return ("import time\nfrom ml.kaggle_physigpt.gan import main as gan, smoke\nbegin = time.time()\n"
                + mount_lookup(owner)
                + f"init = sorted(pathlib.Path(mounted({from_slug!r})).rglob('release.pt'))\n"
                "if len(init) != 1:\n    raise FileNotFoundError(f'expected one release.pt, found {init}')\n"
                f"data = [mounted(slug) for slug in {slugs!r}]\n"
                "print('smoke', json.dumps(smoke('/tmp/gan_smoke')), flush=True)\n"
                f"left = {kernel_hours} - (time.time()-begin)/3600\n"
                f"gan(['--data', *data, '--init', str(init[0]), '--output', '/kaggle/working/gan', '--config', {config!r}, "
                f"*{list(extra)!r}, '--hours', f'{{left:.3f}}'])")
    if kind == "sample":
        if len(datasets) != 1:
            raise ValueError("sample: --datasets names the one dataset holding the checkpoint")
        return (mount_lookup(owner)
                + "import time\nimport numpy as np\nimport torch\n"
                "from ml.kaggle_physigpt.judge_physigpt import SIZES, generate\n"
                f"found = sorted(pathlib.Path(mounted({datasets[0]!r})).rglob({checkpoint!r}))\n"
                f"if len(found) != 1:\n    raise FileNotFoundError(f'expected one {checkpoint}, found {{found}}')\n"
                "if not torch.cuda.is_available():\n    raise SystemExit('sample: no GPU in this kernel')\n"
                "begin = time.time()\n"
                f"parts = [generate(str(found[0]), n, seed, 'cuda', steps={gen_steps}, clamp={not no_clamp})\n"
                "         for n, seed in ((SIZES['fit'], 1_000_000), (SIZES['inner'], 2_000_000),\n"
                "                         (SIZES['eval'], 3_000_000))]\n"
                "generated = np.concatenate(parts)\n"
                "np.save('/kaggle/working/generated.npy', generated.astype(np.float16))\n"
                "np.save('/kaggle/working/generated_float32.npy', generated)\n"
                "print('sampled', generated.shape, 'minutes', (time.time()-begin)/60, flush=True)")
    if cpu and not generated_slug:
        raise ValueError("judge --cpu scores samples drawn elsewhere: it needs --generated-slug")
    if kind == "judge" and generated_slug:
        if judge_seeds != 0:
            raise ValueError("judge --generated-slug is the feature tier only: --judge-seeds 0")
        slugs = [shard_slug(k) for k in shards]+[solo_slug(k) for k in solos]+list(datasets)
        return (mount_lookup(owner)
                + "import os, subprocess\n"
                f"slugs, out = {slugs!r}, '/kaggle/working/eval'\n"
                f"found = sorted(pathlib.Path(mounted({generated_slug!r})).rglob('generated*.npy'))\n"
                "if not found:\n    raise FileNotFoundError('no generated*.npy mounted')\n"
                "data = [mounted(slug) for slug in slugs]\n"
                "for path in found:   # one report per file, in eval/<file stem>\n"
                "    subprocess.run([sys.executable, '-m', 'ml.kaggle_physigpt.judge_physigpt', out+'/'+path.stem,\n"
                "                    '--data', *data, '--mode', 'features', '--generated', str(path), '--device',\n"
                f"                    {'cpu' if cpu else 'cuda'!r}, '--threads', '4'],\n"
                "                   env={**os.environ, 'PYTHONPATH': str(root)}, check=True)\n"
                "print('judge done:', [p.stem for p in found], flush=True)")
    if kind == "judge":
        slugs = [shard_slug(k) for k in shards]+[solo_slug(k) for k in solos]+list(datasets)
        head = (mount_lookup(owner)
                + "import os, subprocess\n"
                f"slugs, out = {slugs!r}, '/kaggle/working/eval'\n"
                f"found = sorted(pathlib.Path(mounted({from_slug or stage_slug(stage)!r})).rglob({checkpoint!r}))\n"
                f"if len(found) != 1:\n    raise FileNotFoundError(f'expected one {checkpoint}, found {{found}}')\n"
                "data = [mounted(slug) for slug in slugs]\n"
                "def run(mode, gpu, *more):\n"
                "    env = {**os.environ, 'CUDA_VISIBLE_DEVICES': gpu, 'PYTHONPATH': str(root)}\n"
                "    argv = [sys.executable, '-m', 'ml.kaggle_physigpt.judge_physigpt', out+'/'+mode, '--data', *data,\n"
                "            '--mode', mode, '--device', 'cuda', '--threads', '4', *more]\n"
                "    return subprocess.Popen(argv, env=env)\n")
        sampling = f"'--gen-steps', '{gen_steps}'" + (", '--no-clamp'" if no_clamp else "")
        if judge_seeds == 0:   # the feature tier only: sample, compare features, no strict judge fit
            return (head+f"codes = [run('features', '0', '--checkpoint', str(found[0]), {sampling}).wait()]\n"
                    "print('judge exit codes (features):', codes, flush=True)\n"
                    "if any(codes):\n    raise SystemExit(f'judge failed: {codes}')")
        return (head
                + f"seeds = {[str(i) for i in range(judge_seeds)]!r}\n"
                + f"model = run('model', '0', '--checkpoint', str(found[0]), '--seeds', *seeds, {sampling})\n"
                + ("controls = None\n" if skip_controls else "controls = run('controls', '1', '--seeds', '0')\n")
                + "codes = [model.wait()]\n"
                "if codes[0] == 0:\n"
                "    codes.append(run('features', '0', '--checkpoint', str(found[0]),\n"
                "                     '--generated', out+'/model/generated.npy').wait())\n"
                "if controls:\n    codes.append(controls.wait())\n"
                "print('judge exit codes (model, features, controls):', codes, flush=True)\n"
                "if any(codes):\n    raise SystemExit(f'judge failed: {codes}')")
    new, replay = (shards, ()) if stage == 0 else (shards[-1:], shards[:-1])
    new = [shard_slug(k) for k in new]+[solo_slug(k) for k in solos]+list(datasets)
    replay = [shard_slug(k) for k in replay]
    args = (f"args = ['--data', *map(mounted, {new!r}), '--replay', *map(mounted, {replay!r}), '--output', "
            f"'/kaggle/working/stage{stage}', '--config', {config!r}, '--epochs', {str(epochs)!r}, *{list(extra)!r}]\n")
    if kind == "tpu":
        text = ("import time\nfrom ml.kaggle_physigpt.train_tpu import main, smoke, versions\nbegin = time.time()\n"
                "print('versions', json.dumps(versions()), flush=True)\n"
                f"print('smoke', json.dumps(smoke('/tmp/physigpt_smoke', {config!r})), flush=True)\n")
        if smoke_only:
            return text+"print('smoke only: no stage trained')"
        if stage > 0:
            raise NotImplementedError("tpu: a later stage mounts the previous stage as in train; not wired yet")
        return (text+mount_lookup(owner)+args
                + f"main(args + ['--hours', f'{{{TPU_HOURS} - (time.time()-begin)/3600:.3f}}'])")
    text = ("import time\nfrom ml.kaggle_physigpt.train import main as train, pick_compile\nbegin = time.time()\n"
            + mount_lookup(owner)+args)
    if kind == "decay" and decay_steps < 1:
        raise ValueError("decay: --decay-steps must be at least 1")
    resume_slug = (from_slug or stage_slug(stage)) if kind == "decay" else stage_slug(stage-1) if stage > 0 else None
    if resume_slug:
        text += (f"stable = sorted(pathlib.Path(mounted({resume_slug!r})).rglob('stable.pt'))\n"
                 "if len(stable) != 1:\n    raise FileNotFoundError(f'expected one stable.pt, found {stable}')\n"
                 "args += ['--resume', str(stable[0])"+(f", '--decay-steps', {str(decay_steps)!r}" + (f", '--hold-steps', {str(hold_steps)!r}" if hold_steps else "")
                                      if kind == "decay" else "")+"]\n")
    micro = list(extra[extra.index("--micro"):extra.index("--micro")+2]) if "--micro" in extra else []
    return (text+f"use, report = pick_compile('/tmp/physigpt_smoke', {config!r}, extra={micro!r})\n"
            "print('smoke', json.dumps(report), flush=True)\n"
            f"left = {kernel_hours} - (time.time()-begin)/3600\n"
            "train(args + (['--compile'] if use else []) + ['--hours', f'{left:.3f}'])")


def stage(output, kind, owner=OWNER, **kw):
    root = Path(__file__).resolve().parents[2]
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip()
    if not branch.startswith("claude/model-benchmark"):
        raise RuntimeError("Stage this experiment from its dedicated branch")
    files = {name: (root/name).read_text() for name in SOURCES[kind]}
    hashes = {p: hashlib.sha256(text.encode()).hexdigest() for p, text in files.items()}
    payload = base64.b64encode(zlib.compress(json.dumps(files).encode())).decode()
    entry = entry_for(kind, owner=owner, **kw)
    for module in re.findall(r"from (ml\.[\w.]+) import", entry):
        if module.replace(".", "/")+".py" not in files:
            raise RuntimeError(f"{kind}: entry imports {module}, which is not staged")
    body = ("import base64, json, pathlib, sys, zlib\n"
            "root = pathlib.Path('/tmp/ppg_research_source')\nroot.mkdir(exist_ok=True)\n"
            f"FILES = json.loads(zlib.decompress(base64.b64decode({payload!r})))\n"
            "for name, text in FILES.items():\n    path = root/name\n    path.parent.mkdir(parents=True, exist_ok=True)\n"
            "    path.write_text(text)\nsys.path.insert(0, str(root))\n"
            f"pathlib.Path('/kaggle/working/source_manifest.json').write_text({json.dumps(dict(branch=branch, files=hashes))!r})\n"
            + entry+"\n")
    # DDP workers are spawned: the generated script must not re-run its body when they import it.
    script = "# Generated by ml/kaggle_physigpt/stage.py\nif __name__ == '__main__':\n" + \
        "\n".join("    "+line for line in body.splitlines())+"\n"
    compile(script, "run.py", "exec")
    dataset_sources = ([f"{owner}/{d}" for d in kw.get("datasets", ())]
                       if kind in ("tpu", "train", "judge", "decay", "gan", "sample") else [])
    if kw.get("generated_slug"):
        dataset_sources.append(f"{owner}/{kw['generated_slug']}")
    if kind == "data":
        k = kw.get("shard", 0)
        meta = dict(id=f"{owner}/{shard_slug(k)}", title=f"PPG physiGPT MIMIC3 Shard{k} v1", enable_gpu=False,
                    kernel_sources=[])
    elif kind == "solo":
        k = kw.get("shard", 0)
        meta = dict(id=f"{owner}/{solo_slug(k)}", title=f"PPG physiGPT Solo{k} v1", enable_gpu=True,
                    machine_shape="NvidiaTeslaT4", kernel_sources=[])
    elif kind == "solotrain":
        k = kw.get("shard", 0)
        meta = dict(id=f"{owner}/{solotrain_slug(k)}", title=f"PPG physiGPT Solo{k} Train v1", enable_gpu=True,
                    machine_shape="NvidiaTeslaT4", kernel_sources=[f"{owner}/{solo_slug(k)}"])
    elif kind == "decay":
        k = kw.get("stage", 0)
        name = f"ppg-physigpt-decay{k}-{kw['tag']}-v1" if kw.get("tag") else decay_slug(k)
        meta = dict(id=f"{owner}/{name}", title=name if kw.get("tag") else f"PPG physiGPT Decay{k} v1", enable_gpu=True,
                    machine_shape="NvidiaTeslaT4", kernel_sources=[f"{owner}/{shard_slug(s)}" for s in kw.get("shards", (0,))]
                    + [f"{owner}/{solo_slug(s)}" for s in kw.get("solos", ())]
                    + [f"{owner}/{kw.get('from_slug') or stage_slug(k)}"])
    elif kind in ("rsrgan", "rsrfid"):
        name = "ppg-app-fidelity-v1" if kind == "rsrfid" else f"ppg-{kw.get('tag') or 'rsr-flowgan'}-v1"
        dataset_sources = [f"{owner}/{d}" for d in RSR_DATASETS]
        meta = dict(id=f"{owner}/{name}", title=name, enable_gpu=True, machine_shape="NvidiaTeslaT4", kernel_sources=[])
    elif kind == "gan":
        name = f"ppg-physigpt-{kw.get('tag') or 'apft-gan'}-v1"
        meta = dict(id=f"{owner}/{name}", title=name, enable_gpu=True, machine_shape="NvidiaTeslaT4",
                    kernel_sources=[f"{owner}/{shard_slug(s)}" for s in kw.get("shards", (0,))]
                    + [f"{owner}/{solo_slug(s)}" for s in kw.get("solos", ())] + [f"{owner}/{kw['from_slug']}"])
    elif kind == "sample":
        name = f"ppg-physigpt-{kw['tag']}-sample-v1"
        meta = dict(id=f"{owner}/{name}", title=name, enable_gpu=True, machine_shape="NvidiaTeslaT4", kernel_sources=[])
    elif kind == "judge" and kw.get("generated_slug"):
        name = f"ppg-physigpt-judge-{kw['generated_slug'].removeprefix('ppg-physigpt-')}-fid"
        meta = dict(id=f"{owner}/{name}", title=name, enable_gpu=not kw.get("cpu"),
                    kernel_sources=[f"{owner}/{shard_slug(s)}" for s in kw.get("shards", (0,))]
                    + [f"{owner}/{solo_slug(s)}" for s in kw.get("solos", ())])
        if not kw.get("cpu"):
            meta["machine_shape"] = "NvidiaTeslaT4"
    elif kind == "judge":
        k = kw.get("stage", 0)
        source = kw.get("from_slug") or stage_slug(k)
        own = source == stage_slug(k)
        judge = f"ppg-physigpt-judge{k}-v1" if own else f"ppg-physigpt-judge-{source.removeprefix('ppg-physigpt-')}"
        if kw.get("gen_steps", 32) != 32:
            judge += f"-g{kw['gen_steps']}"
        if kw.get("no_clamp"):
            judge += "-noclamp"
        if kw.get("judge_seeds", 3) == 0:
            judge += "-fid"
        # Kaggle takes the kernel's slug from its title, so a title that is not the id's own slug splits them.
        meta = dict(id=f"{owner}/{judge}", title=f"PPG physiGPT Judge{k} v1" if judge == f"ppg-physigpt-judge{k}-v1" else judge,
                    enable_gpu=True,
                    machine_shape="NvidiaTeslaT4", kernel_sources=[f"{owner}/{shard_slug(s)}" for s in kw.get("shards", (0,))]
                    + [f"{owner}/{solo_slug(s)}" for s in kw.get("solos", ())] + [f"{owner}/{source}"])
    elif kind == "tpu":
        k = kw.get("stage", 0)
        smoke_only = kw.get("smoke_only", False)
        meta = dict(id=f"{owner}/{'ppg-physigpt-tpu-smoke-v1' if smoke_only else tpu_slug(k)}",
                    title="PPG physiGPT TPU Smoke v1" if smoke_only else f"PPG physiGPT TPU Stage{k} v1",
                    enable_gpu=False, machine_shape="Tpu1VmV38",
                    kernel_sources=[] if smoke_only else [f"{owner}/{shard_slug(s)}" for s in kw.get("shards", (0,))]
                    + [f"{owner}/{solo_slug(s)}" for s in kw.get("solos", ())])
    else:
        k = kw.get("stage", 0)
        # A tagged stage (another config on the same data) keeps its own output; the title is the id's own slug.
        name = f"ppg-physigpt-stage{k}-{kw['tag']}-v1" if kw.get("tag") else stage_slug(k)
        meta = dict(id=f"{owner}/{name}", title=name if kw.get("tag") else f"PPG physiGPT Stage{k} v1", enable_gpu=True,
                    machine_shape="NvidiaTeslaT4", kernel_sources=[f"{owner}/{shard_slug(s)}" for s in kw.get("shards", (0,))]
                    + [f"{owner}/{solo_slug(s)}" for s in kw.get("solos", ())]
                    + ([f"{owner}/{stage_slug(k-1)}"] if k > 0 else []))
    meta.update(code_file="run.py", language="python", kernel_type="script", is_private=True, enable_tpu=kind == "tpu",
                enable_internet=True, dataset_sources=dataset_sources, competition_sources=[], model_sources=[])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/"run.py").write_text(script)
    (output/"kernel-metadata.json").write_text(json.dumps(meta, indent=2)+"\n")
    (output/"source_manifest.json").write_text(json.dumps(dict(branch=branch, files=hashes), indent=2)+"\n")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("kind", choices=sorted(SOURCES))
    parser.add_argument("--owner", default=OWNER)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--stop", type=int, default=10**9)
    parser.add_argument("--cap", type=int, default=300)
    parser.add_argument("--target", type=int, default=5_000_000)
    parser.add_argument("--hours", type=float, default=10.5)
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--shards", type=int, nargs="+", default=[0])
    parser.add_argument("--solos", type=int, nargs="*", default=[], help="solo k outputs mounted as new data too")
    parser.add_argument("--datasets", nargs="*", default=[], help="Kaggle dataset slugs (same owner) as new data too")
    parser.add_argument("--kernel-hours", type=float, default=KERNEL_HOURS,
                        help="train: time budget of the kernel; keep it under the remaining GPU quota")
    parser.add_argument("--config", default="base")
    parser.add_argument("--epochs", type=float, default=4.)
    parser.add_argument("--smoke-only", action="store_true", help="tpu: versions and the synthetic smoke run only")
    parser.add_argument("--plateau", type=int, default=0, help="train.py --plateau (evaluations of patience)")
    parser.add_argument("--checkpoint", default="release.pt", help="judge: checkpoint file of the stage output")
    parser.add_argument("--judge-seeds", type=int, default=3, help="judge: judge seeds for the generated source")
    parser.add_argument("--decay-steps", type=int, default=0,
                        help="decay: steps of lr decay after the stage's stable.pt (kind decay resumes it)")
    parser.add_argument("--hold-steps", type=int, default=0, help="decay: steps at the peak rate before the decay")
    parser.add_argument("--tag", default="", help="train/decay: suffix of the kernel id, so a variant keeps its own output")
    parser.add_argument("--micro", type=int, default=0, help="train.py --micro, also for the smoke runs (0: off)")
    parser.add_argument("--lr", type=float, default=0., help="train.py --lr (0: its default)")
    parser.add_argument("--diff-weight", type=float, default=0., help="train.py --diff-weight (0: off)")
    parser.add_argument("--gen-steps", type=int, default=32, help="judge: Heun steps per patch of the generator")
    parser.add_argument("--no-clamp", action="store_true", help="judge: sample patches without clipping to [0, 1]")
    parser.add_argument("--skip-controls", action="store_true", help="judge: do not rerun the model-independent controls")
    parser.add_argument("--from-slug", default=None, help="judge: kernel whose release.pt is judged (default: the stage)")
    parser.add_argument("--generated-slug", default=None,
                        help="judge: dataset (same owner) of generated*.npy to score on the feature tier, no checkpoint")
    parser.add_argument("--cpu", action="store_true", help="judge: run on CPU, spending no GPU quota (needs --generated-slug)")
    parser.add_argument("--plateau-delta", type=float, default=0., help="train.py --plateau-delta (0: its default)")
    parser.add_argument("--eval-every", type=int, default=0, help="train.py --eval-every (0: its default)")
    parser.add_argument("--gan-steps", type=int, default=0, help="gan: gan.py --steps (0: its default)")
    parser.add_argument("--adv-weight", type=float, default=0., help="gan: gan.py --adv-weight (0: its default)")
    parser.add_argument("--patience", type=int, default=0, help="gan: gan.py --patience (0: no early stop)")
    args = parser.parse_args(argv)
    data = dict(shard=args.shard, start=args.start, stop=args.stop, cap=args.cap, target=args.target, hours=args.hours)
    train = dict(stage=args.stage, shards=tuple(args.shards), solos=tuple(args.solos), config=args.config,
                 epochs=args.epochs, datasets=tuple(args.datasets), kernel_hours=args.kernel_hours,
                 checkpoint=args.checkpoint, judge_seeds=args.judge_seeds, decay_steps=args.decay_steps,
                 from_slug=args.from_slug, gen_steps=args.gen_steps, skip_controls=args.skip_controls, no_clamp=args.no_clamp, hold_steps=args.hold_steps, tag=args.tag,
                 generated_slug=args.generated_slug, cpu=args.cpu)
    extra = ((["--plateau", str(args.plateau)] if args.plateau else [])
             + (["--plateau-delta", str(args.plateau_delta)] if args.plateau_delta else [])
             + (["--eval-every", str(args.eval_every)] if args.eval_every else [])
             + (["--diff-weight", str(args.diff_weight)] if args.diff_weight else [])
             + (["--micro", str(args.micro)] if args.micro else [])
             + (["--lr", str(args.lr)] if args.lr else []))
    train["extra"] = tuple(extra)
    gan = dict(train, extra=tuple((["--steps", str(args.gan_steps)] if args.gan_steps else [])
                                  + (["--adv-weight", str(args.adv_weight)] if args.adv_weight else [])
                                  + (["--lr", str(args.lr)] if args.lr else [])
                                  + (["--eval-every", str(args.eval_every)] if args.eval_every else [])
                                  + (["--patience", str(args.patience)] if args.patience else [])
                                  + ["--gen-steps", str(args.gen_steps)]))
    rsrgan = dict(kernel_hours=args.kernel_hours, tag=args.tag,
                  extra=tuple((["--steps", str(args.gan_steps)] if args.gan_steps else [])
                              + (["--adv-weight", str(args.adv_weight)] if args.adv_weight else [])
                              + (["--lr", str(args.lr)] if args.lr else [])
                              + (["--eval-every", str(args.eval_every)] if args.eval_every else [])))
    sample = dict(datasets=tuple(args.datasets), checkpoint=args.checkpoint, gen_steps=args.gen_steps,
                  no_clamp=args.no_clamp, tag=args.tag)
    kw = dict(data=data, train=train, judge=train, sample=sample, decay=train, gan=gan, rsrgan=rsrgan, rsrfid={}, tpu=dict(train, smoke_only=args.smoke_only),
              solo=dict(data, config=args.config, epochs=args.epochs, extra=tuple(extra)),
              solotrain=dict(shard=args.shard, config=args.config, epochs=args.epochs, extra=tuple(extra)))[args.kind]
    print(stage(args.output, args.kind, args.owner, **kw))


if __name__ == "__main__":
    main()
