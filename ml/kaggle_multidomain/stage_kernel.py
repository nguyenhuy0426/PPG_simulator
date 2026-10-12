"""Package exact local research sources into one reproducible private Kaggle script."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zlib


def stage(output, mode, steps=2000, seeds=(42, 123, 2026), arm=None):
    root = Path(__file__).resolve().parents[2]
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip()
    # Research kernels are staged only from an experiment branch, never from main or a detached HEAD.
    if not branch.startswith(("codex/ppg-multidomain", "claude/model-benchmark")):
        raise RuntimeError("Stage this experiment from its dedicated branch")
    sources = ["ml/kaggle_lsm/train_lsm.py", "ml/kaggle_multidomain/data.py", "ml/kaggle_multidomain/view.py",
               "ml/kaggle_multidomain/bidmc_split.json"]
    flow = mode.startswith(("flow10_", "flow10b_", "flow10c_", "flow10d_"))
    if mode == "flow10c_resume":
        # The final trained every seed but its worker pool died while scoring two of them.
        mode_args = ["--stage", "final", "--resume-from", "/kaggle/input"]
    physio = flow or mode.startswith(("physio_", "physio3_", "physio4", "physio5", "physio6", "physio7", "physio8",
                                      "physio9"))
    if mode == "train" or physio:
        sources += [f"ml/kaggle_multidomain/{name}.py" for name in ("models", "benchmark", "train", "report")]
    if physio:
        sources += [f"ml/kaggle_multidomain/{name}.py" for name in ("data_more", "physio", "experiment", "report_more")]
        sources += [f"ml/kaggle_multidomain/{name}_sources.json" for name in ("wrist", "capnobase")]
    if flow or mode.startswith(("physio3_", "physio4", "physio5", "physio6", "physio7", "physio8", "physio9")):
        sources += ["ml/kaggle_multidomain/data_gxu.py"]
    if flow or mode in ("physio3_pilot", "physio3_final", "physio4", "physio5", "physio6", "physio7", "physio8", "physio9"):
        # experiment_v3 imports the PhysioFlow model for its flow arms.
        sources += [f"ml/kaggle_multidomain/{name}.py" for name in ("labels", "control", "experiment_v3", "evaluate_v3",
                                                                     "report_v3", "flow")]
        sources += ["models/__init__.py", "models/waveform.py", "models/limits.py"]
    if flow or mode in ("physio4", "physio5", "physio6", "physio7", "physio8", "physio9"):
        sources.append("ml/kaggle_multidomain/experiment_v4.py")
    if flow or mode in ("physio5", "physio6", "physio7", "physio8", "physio9"):
        sources.append("ml/kaggle_multidomain/experiment_v5.py")
    if flow:
        sources.append("ml/kaggle_multidomain/experiment_flow.py")
    files = {name: (root/name).read_text() for name in sources}
    payload = base64.b64encode(zlib.compress(json.dumps(files).encode())).decode()
    hashes = {p: hashlib.sha256(text.encode()).hexdigest() for p, text in files.items()}
    entry = ("from ml.kaggle_multidomain.data import prepare\nprepare('/tmp/ppg_raw', '/kaggle/working/ppg_data')"
             if mode == "prepare" else
             f"from ml.kaggle_multidomain.train import main\nmain(['--input-root','/kaggle/input','--output','/kaggle/working/benchmark','--gpus','2','--steps','{steps}','--seeds',"+
             ",".join(repr(str(s)) for s in seeds)+"])")
    if mode == "physio_prepare":
        entry = "from ml.kaggle_multidomain.data_more import prepare\nprepare('/kaggle/input', '/tmp/physio_raw', '/kaggle/working/physio_data')"
    if mode == "physio3_prepare":
        # One chained v3 view: every source re-windowed with the same DC-safe band-pass, then GXU.
        entry = ("from ml.kaggle_multidomain import data, data_more, data_gxu\n"
                 "_, base = data.prepare('/tmp/v3/cache', '/tmp/v3/base', True, 'v3')\n"
                 "_, more = data_more.prepare('/tmp/v3/base', '/tmp/v3/cache', '/tmp/v3/more', 'v3', base['windows_sha256'])\n"
                 "data_gxu.prepare('/tmp/v3/more', '/tmp/v3/cache', '/kaggle/working/physio3_data', None, 'v3', "
                 "more['windows_sha256'], 'ppg_physiomix_v3')")
    if mode in ("physio3_pilot", "physio3_final"):
        stage = mode.split("_")[1]
        args = ["--input-root", "/kaggle/input", "--output", "/kaggle/working/physiomix3", "--stage", stage,
                "--steps", str(steps), "--pilot-steps", str(steps), "--seeds", *map(str, seeds)]
        if stage == "final":
            args += ["--pilot-root", "/kaggle/input"]
        entry = f"from ml.kaggle_multidomain.experiment_v3 import main\nmain({args!r})"
    if mode == "physio4":
        args = ["--input-root", "/kaggle/input", "--output", "/kaggle/working/physiomix4", "--steps", str(steps),
                "--seeds", *map(str, seeds)]
        entry = f"from ml.kaggle_multidomain.experiment_v4 import main\nmain({args!r})"
    if mode == "physio5":
        args = ["--input-root", "/kaggle/input", "--round4-root", "/kaggle/input", "--output", "/kaggle/working/physiomix5",
                "--steps", str(steps), "--seeds", *map(str, seeds)]
        entry = f"from ml.kaggle_multidomain.experiment_v5 import main\nmain({args!r})"
    if mode == "physio7":
        args = ["--input-root", "/kaggle/input", "--round4-root", "/kaggle/input", "--incumbent-root", "/kaggle/input",
                "--output", "/kaggle/working/physiomix7", "--steps", str(steps), "--seeds", *map(str, seeds),
                "--variant", "crop_r1w"]
        entry = f"from ml.kaggle_multidomain.experiment_v5 import main\nmain({args!r})"
    if mode == "physio9":
        args = ["--input-root", "/kaggle/input", "--round4-root", "/kaggle/input", "--incumbent-root", "/kaggle/input",
                "--output", "/kaggle/working/physiomix9", "--steps", str(steps), "--seeds", *map(str, seeds),
                "--variant", "crop_r1w_motion_dom"]
        entry = f"from ml.kaggle_multidomain.experiment_v5 import main\nmain({args!r})"
    if mode == "physio8":
        args = ["--input-root", "/kaggle/input", "--round4-root", "/kaggle/input", "--incumbent-root", "/kaggle/input",
                "--output", "/kaggle/working/physiomix8", "--steps", str(steps), "--seeds", *map(str, seeds),
                "--variant", "crop_r1w_motion"]
        entry = f"from ml.kaggle_multidomain.experiment_v5 import main\nmain({args!r})"
    if mode == "physio6":
        args = ["--input-root", "/kaggle/input", "--round4-root", "/kaggle/input", "--output", "/kaggle/working/physiomix6",
                "--steps", str(steps), "--seeds", *map(str, seeds), "--variant", "crop_r1"]
        entry = f"from ml.kaggle_multidomain.experiment_v5 import main\nmain({args!r})"
    if flow:
        stage = mode.split("_")[1]
        args = ["--input-root", "/kaggle/input", "--output", "/kaggle/working/physioflow10", "--stage", stage,
                "--steps", str(steps), "--interval", "2000"]
        if mode == "flow10b_pilot":
            # Loop 2 (after pilot 1): flag-gated scaffold arms; guidance 1.5 lost on every pilot-1 arm, so it is dropped.
            args += ["--arms", "F3_flow_flag_deriv", "F4_flow_flag_deriv03", "--samplers"]
            args += [f"{arm}_s{s}_w1" for arm in ("F3_flow_flag_deriv", "F4_flow_flag_deriv03") for s in (8, 16)]
        if mode == "flow10c_resume":
            args = ["--input-root", "/kaggle/input", "--output", "/kaggle/working/physioflow10", *mode_args]
        if mode == "flow10c_pilot":
            # Loop 3: flow-time distributions that reach small t, plus the stop-at-0.04 + data-view-filter finish.
            arms = ("F5_flow_flag_deriv_mix", "F6_flow_flag_deriv_unif")
            args += ["--arms", *arms, "--samplers"]
            args += [f"{arm}_s{s}" for arm in arms for s in ("8_w1", "16_w1", "16_w1_f04")]
        if mode == "flow10d_pilot":
            # Loop 5 (wrist): the low-t stop-band log-PSD loss at weights 1 and 3 on the frozen round-10 sampler,
            # judged against the pre-registered go limits for a 3-seed final.
            arms = ("F7_flow_unif_stop1", "F8_flow_unif_stop3")
            args += ["--arms", *arms, "--samplers", *[f"{arm}_s16_w1" for arm in arms], "--go"]
        if stage == "final":
            args += ["--pilot-root", "/kaggle/input", "--incumbent-root", "/kaggle/input", "--seeds", *map(str, seeds)]
            args += ["--arm", arm] if arm else []
            args += ["--go"] if mode == "flow10d_final" else []
        entry = f"from ml.kaggle_multidomain.experiment_flow import main\nmain({args!r})"
    if mode == "physio_train":
        entry = ("from ml.kaggle_multidomain.experiment import main\n"+
                 f"main(['--input-root','/kaggle/input','--output','/kaggle/working/physiomix','--steps','{steps}','--seeds',"+
                 ",".join(repr(str(s)) for s in seeds)+"])")
    # The entry point's own module must travel in the payload (a missing one fails only on Kaggle).
    for module in re.findall(r"from (ml\.[\w.]+) import", entry):
        if module.replace(".", "/")+".py" not in files:
            raise RuntimeError(f"{mode}: entry imports {module}, which is not staged")
    script = """# Generated by stage_kernel.py; source hashes accompany this script.
import base64, json, pathlib, sys, zlib, subprocess
root = pathlib.Path('/tmp/ppg_research_source')
root.mkdir(exist_ok=True)
FILES = json.loads(zlib.decompress(base64.b64decode(PAYLOAD)))
for name, text in FILES.items():
    path = root/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
sys.path.insert(0, str(root))
""".replace("PAYLOAD", repr(payload))
    if mode in ("prepare", "physio_prepare", "physio3_prepare"):
        script += "subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'wfdb==4.3.1', 'h5py>=3.10,<4'], check=True)\n"
    script += f"pathlib.Path('/kaggle/working/source_manifest.json').write_text({json.dumps(dict(branch=branch, files=hashes))!r})\n"+entry+"\n"
    if flow or mode in ("train", "physio_train", "physio3_pilot", "physio3_final", "physio4", "physio5", "physio6", "physio7", "physio8", "physio9"):
        script = "if __name__ == '__main__':\n"+"\n".join("    "+line for line in script.splitlines())+"\n"
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/"run.py").write_text(script)
    metadata = json.loads(Path(__file__).with_name("kernel-metadata.json").read_text())
    metadata.update(code_file="run.py", enable_gpu=flow or mode in ("train", "physio_train", "physio3_pilot", "physio3_final",
                                                                    "physio4", "physio5", "physio6", "physio7", "physio8",
                                                                    "physio9"))
    if mode == "prepare":
        metadata.update(id="charlesday2612/ppg-multidomain-data-v1", title="PPG Multidomain Data v1", kernel_sources=[])
    if mode == "physio_prepare":
        metadata.update(id="charlesday2612/ppg-physiomix-data-v1", title="PPG PhysioMix Data v1",
                        kernel_sources=["charlesday2612/ppg-multidomain-data-v1"])
    if mode == "physio3_prepare":
        metadata.update(id="charlesday2612/ppg-physiomix3-data-v1", title="PPG PhysioMix3 Data v1", kernel_sources=[])
    if mode == "physio3_pilot":
        metadata.update(id="charlesday2612/ppg-physiomix3-pilot-v1", title="PPG PhysioMix3 Pilot v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1"])
    if mode == "physio3_final":
        metadata.update(id="charlesday2612/ppg-physiomix3-benchmark-v1", title="PPG PhysioMix3 Benchmark v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1", "charlesday2612/ppg-physiomix3-pilot-v1"])
    if mode == "physio4":
        metadata.update(id="charlesday2612/ppg-physiomix4-lr-v1", title="PPG PhysioMix4 LR v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1"])
    if mode == "physio5":
        metadata.update(id="charlesday2612/ppg-physiomix5-crop-v1", title="PPG PhysioMix5 Crop v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1", "charlesday2612/ppg-physiomix4-lr-v1"])
    if mode == "physio6":
        metadata.update(id="charlesday2612/ppg-physiomix6-r1-v1", title="PPG PhysioMix6 R1 v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1", "charlesday2612/ppg-physiomix4-lr-v1"])
    if mode == "physio7":
        metadata.update(id="charlesday2612/ppg-physiomix7-r1w-v1", title="PPG PhysioMix7 R1w v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1", "charlesday2612/ppg-physiomix4-lr-v1",
                                        "charlesday2612/ppg-physiomix6-r1-v1"])
    if mode == "physio9":
        # Round 8 did not ship; round 7 stays the only mounted DECISION_ROUND5.json (the incumbent).
        metadata.update(id="charlesday2612/ppg-physiomix9-motion-dom-v1", title="PPG PhysioMix9 Motion Dom v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1", "charlesday2612/ppg-physiomix4-lr-v1",
                                        "charlesday2612/ppg-physiomix7-r1w-v1"])
    if mode == "physio8":
        # Only round 7 may carry a DECISION_ROUND5.json among the inputs: it is the incumbent.
        metadata.update(id="charlesday2612/ppg-physiomix8-motion-v1", title="PPG PhysioMix8 Motion v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1", "charlesday2612/ppg-physiomix4-lr-v1",
                                        "charlesday2612/ppg-physiomix7-r1w-v1"])
    if mode == "flow10_pilot":
        metadata.update(id="charlesday2612/ppg-physioflow10-pilot-v1", title="PPG PhysioFlow10 Pilot v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1"])
    if mode == "flow10b_pilot":
        metadata.update(id="charlesday2612/ppg-physioflow10b-pilot-v1", title="PPG PhysioFlow10b Pilot v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1"])
    if mode == "flow10c_pilot":
        metadata.update(id="charlesday2612/ppg-physioflow10c-pilot-v1", title="PPG PhysioFlow10c Pilot v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1"])
    if mode == "flow10d_pilot":
        metadata.update(id="charlesday2612/ppg-physioflow10d-pilot-v1", title="PPG PhysioFlow10d Pilot v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1"])
    if mode == "flow10d_final":
        metadata.update(id="charlesday2612/ppg-physioflow10d-final-v1", title="PPG PhysioFlow10d Final v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1", "charlesday2612/ppg-physioflow10d-pilot-v1",
                                        "charlesday2612/ppg-physiomix9-motion-dom-v1"])
    if mode == "flow10c_resume":
        metadata.update(id="charlesday2612/ppg-physioflow10c-resume-v1", title="PPG PhysioFlow10c Resume v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1", "charlesday2612/ppg-physioflow10c-final-v1"])
    if mode == "flow10c_final":
        metadata.update(id="charlesday2612/ppg-physioflow10c-final-v1", title="PPG PhysioFlow10c Final v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1", "charlesday2612/ppg-physioflow10c-pilot-v1",
                                        "charlesday2612/ppg-physiomix9-motion-dom-v1"])
    if mode == "flow10b_final":
        metadata.update(id="charlesday2612/ppg-physioflow10b-final-v1", title="PPG PhysioFlow10b Final v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1", "charlesday2612/ppg-physioflow10b-pilot-v1",
                                        "charlesday2612/ppg-physiomix9-motion-dom-v1"])
    if mode == "flow10_final":
        # Round 9's output supplies the incumbent (its DECISION_ROUND5.json); the pilot supplies the frozen sampler.
        metadata.update(id="charlesday2612/ppg-physioflow10-final-v1", title="PPG PhysioFlow10 Final v1",
                        kernel_sources=["charlesday2612/ppg-physiomix3-data-v1", "charlesday2612/ppg-physioflow10-pilot-v1",
                                        "charlesday2612/ppg-physiomix9-motion-dom-v1"])
    if mode == "physio_train":
        metadata.update(id="charlesday2612/ppg-physiomix-benchmark-v1", title="PPG PhysioMix Benchmark v1",
                        kernel_sources=["charlesday2612/ppg-physiomix-data-v1"])
    (output/"kernel-metadata.json").write_text(json.dumps(metadata, indent=2)+"\n")
    (output/"source_manifest.json").write_text(json.dumps(dict(branch=branch, files=hashes), indent=2)+"\n")
    compile(script, str(output/"run.py"), "exec")
    return output


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--mode", choices=("prepare", "train", "physio_prepare", "physio_train", "physio3_prepare",
                                      "physio3_pilot", "physio3_final", "physio4", "physio5", "physio6", "physio7", "physio8", "physio9",
                                      "flow10_pilot", "flow10_final", "flow10b_pilot", "flow10b_final", "flow10c_pilot",
                                      "flow10c_final", "flow10c_resume", "flow10d_pilot", "flow10d_final"), required=True)
    p.add_argument("--steps", type=int)
    p.add_argument("--seeds", type=int, nargs="+", default=[42, 123, 2026])
    p.add_argument("--arm", help="Flow final: the sampler arm chosen across pilot loops")
    a = p.parse_args()
    default = {"physio_train": 6000, "physio3_final": 6000, "physio3_pilot": 3000, "physio4": 20000,
               "physio5": 20000, "physio6": 20000,
               "physio7": 20000, "physio8": 20000, "physio9": 20000, "flow10_pilot": 16000,
               "flow10_final": 16000, "flow10b_pilot": 20000, "flow10b_final": 20000, "flow10c_pilot": 20000,
               "flow10c_final": 20000, "flow10d_pilot": 20000, "flow10d_final": 20000}.get(a.mode, 2000)
    print(stage(a.output, a.mode, a.steps or default, a.seeds, a.arm))
