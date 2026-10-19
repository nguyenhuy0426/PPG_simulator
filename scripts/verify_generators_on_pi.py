#!/usr/bin/env python3
"""
scripts/verify_generators_on_pi.py — do the shipped generators compute, on this machine, the
strips they compute on the laptop, and how long do they take?

Run it on the Raspberry Pi, inside the Pi's own .venv, with the simulator closed (a running
app competes for the CPU and inflates the timing):

    .venv/bin/python scripts/verify_generators_on_pi.py --out docs/hardware-validation/<date>/generators.json

For PhysioMix, PhysioFlow and LSM-GAN (assets/neural) it
  1. runs the generator worker that the Neural page starts (python -m core.sequence_worker)
     from process start to its answer, against the time after which that page gives up;
  2. loads the model with the app's own loader (core/neural_preview.py), which compares the
     file's SHA-256 with assets/neural/manifest.json;
  3. feeds the noise vectors and conditions stored in the laptop reference
     (assets/neural/generator_reference.json) to the model and compares the strips with the
     laptop's, sample by sample;
  4. checks that the app's own generate() and its seeded noise return the laptop strips (torch
     draws the noise with other float rounding on a CPU without AVX2, so the noise is compared
     as a number and only the strips are judged);
  5. times one 30 s strip as Table 1 of the paper does: one thread, one warm-up, median of
     seven runs.

It never opens I2C, GPIO or a DAC. A PASS shows that this CPU and PyTorch build compute the
laptop's strips within the tolerance. It says nothing about DAC voltages, LED current or the
optical path.

Exit status: 0 if no check FAILED, 1 otherwise.

The reference is made on the laptop whenever a model in assets/neural changes:

    PPG_DRY_RUN=1 .venv/bin/python scripts/verify_generators_on_pi.py --make-reference
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import signal
import statistics
import subprocess
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402  (constants only)
from core.sequence_worker import WORKER_TIMEOUT_S  # noqa: E402  (argparse and json only)

REFERENCE = PROJECT_ROOT / "assets" / "neural" / "generator_reference.json"
NEURAL_REQUIREMENTS = PROJECT_ROOT / "requirements" / "neural.txt"
LABELS = {"physiomix": "PhysioMix", "physioflow": "PhysioFlow", "lsm": "LSM-GAN"}
# (seed, dataset, rate in bpm) at the dataset's default irregularity, as the Neural page asks
# for strips: a finger pulse, an irregular rhythm, wrist motion above the 40-135 bpm of the
# training labels, and both ends of the supported 40-180 bpm.
CASES = ((11, "gxu_finger", 75.), (12, "perform_af", 110.), (13, "wrist", 150.),
         (14, "bidmc", 40.), (15, "perform_large", 180.))
LSM_SEEDS = (11, 12)  # LSM-GAN takes no condition
# Largest accepted difference to a laptop strip, in the generators' normalised 0-1 units. On the
# laptop, changing the thread count or the convolution kernels moves a strip by at most 2.4e-6;
# 1e-3 is 45 uV at the default 45 mV infrared amplitude, under 0.06 of a DAC step.
TOLERANCE = 1e-3
# The app plays a strip x as 1.5 V + 45 mV * x on the infrared DAC (core/neural_preview.py).
IR_DC_V, IR_AC_V = 1.5, 0.045
ARM_PARTS = {"0xd03": "Cortex-A53", "0xd08": "Cortex-A72", "0xd0b": "Cortex-A76"}  # /proc/cpuinfo "CPU part"

_RESULTS = []
_GREEN, _RED, _YELLOW, _CYAN, _OFF = ("\033[1;32m", "\033[1;31m", "\033[1;33m", "\033[1;36m", "\033[0m")


def _paint(colour: str, text: str) -> str:
    return f"{colour}{text}{_OFF}" if sys.stdout.isatty() and os.environ.get("NO_COLOR") is None else text


def section(title: str) -> None:
    print(f"\n{_paint(_CYAN, '==> ' + title)}", flush=True)


def record(status: str, label: str, detail: str = "") -> None:
    colour = {"PASS": _GREEN, "FAIL": _RED, "SKIP": _YELLOW}[status]
    print(f"  [{_paint(colour, status)}] {label}")
    for line in detail.splitlines():
        print(f"        {line}")
    sys.stdout.flush()
    _RESULTS.append(dict(status=status, label=label, detail=detail))


# ---------------------------------------------------------------------------
# Machine
# ---------------------------------------------------------------------------

def pinned_torch(machine: str, requirements: Path = NEURAL_REQUIREMENTS) -> str | None:
    """The torch version that requirements/neural.txt pins for this architecture, or None."""
    try:
        lines = requirements.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        match = re.match(r"\s*torch==([\w.]+)\s*;\s*platform_machine\s*(==|!=)\s*['\"]([^'\"]+)['\"]", line)
        if match and (machine == match.group(3)) == (match.group(2) == "=="):
            return match.group(1)
    return None


def _installed(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def describe_machine() -> dict:
    """CPU, board and versions, read without importing torch."""
    info = dict(platform=platform.platform(), machine=platform.machine(), python=platform.python_version(),
                cores=os.cpu_count(), torch=_installed("torch"), numpy=_installed("numpy"))
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
    except OSError:
        cpuinfo = ""
    name = re.search(r"^model name\s*:\s*(.+)$", cpuinfo, re.M)
    parts = sorted(set(re.findall(r"^CPU part\s*:\s*(0x[0-9a-fA-F]+)$", cpuinfo, re.M)))
    info["cpu"] = (name.group(1).strip() if name else ", ".join(ARM_PARTS.get(p.lower(), p) for p in parts)
                   or platform.processor() or "unknown")
    try:
        info["board"] = Path("/proc/device-tree/model").read_text().rstrip("\x00\n")
    except OSError:
        pass
    return info


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def _pack(values) -> str:
    """Exact float32 values (little-endian) as base64 text for the JSON reference."""
    import numpy as np
    return base64.b64encode(np.asarray(values, dtype="<f4").tobytes()).decode("ascii")


def _unpack(text: str):
    import numpy as np
    return np.frombuffer(base64.b64decode(text), dtype="<f4")


def load_generator(name: str):
    from core.neural_preview import LSMSequenceGenerator, PhysioMixGenerator
    return LSMSequenceGenerator() if name == "lsm" else PhysioMixGenerator(slot=name)


def seeded_noise(torch, seed: int):
    """The noise vector the app draws for a seed (core/neural_preview.py)."""
    return torch.randn(1, 1200, generator=torch.Generator(device="cpu").manual_seed(seed))


def model_strip(generator, noise, condition):
    """Raw model output (1200 values) for a given noise vector and condition."""
    import numpy as np
    torch = generator.torch
    z = torch.from_numpy(np.array(noise, dtype=np.float32)).reshape(1, 1200)
    with torch.inference_mode():
        wave = generator.model(z) if condition is None else generator.model(z, torch.tensor([condition]))
    if tuple(wave.shape) != (1, 1, 1200):
        raise ValueError(f"output shape {tuple(wave.shape)}, expected (1, 1, 1200)")
    return wave[0, 0].numpy().astype(np.float64)


def app_ir_volts(generator, case: dict):
    """Infrared voltages that the app's own generate() returns for a reference case."""
    import numpy as np
    preview = (generator.generate(case["seed"]) if case["condition"] is None
               else generator.generate(case["seed"], case["heart_rate"], case["domain"]))
    return np.array([row[1] for row in preview.samples], dtype=np.float64)


def ir_volts(strip):
    """The app's infrared mapping, in float64 like the app (a float32 sum would be off by ~0.1 uV)."""
    import numpy as np
    return IR_DC_V + IR_AC_V * np.clip(np.asarray(strip, dtype=np.float64), 0., 1.)


def run_worker(name: str, case: dict) -> dict:
    """The worker the Neural page starts, timed from process start to its JSON answer."""
    import numpy as np
    command = [sys.executable, "-m", "core.sequence_worker", str(case["seed"]), "--model", name]
    if case["condition"] is not None:
        command += ["--hr", f"{case['heart_rate']:g}", "--domain", case["domain"]]
    started = time.perf_counter()
    try:
        done = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=WORKER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return dict(seconds=None, timeout_s=WORKER_TIMEOUT_S, error=f"no answer within {WORKER_TIMEOUT_S} s")
    result = dict(seconds=time.perf_counter() - started, timeout_s=WORKER_TIMEOUT_S, returncode=done.returncode)
    if done.returncode < 0:
        try:
            killed = signal.Signals(-done.returncode).name
        except ValueError:
            killed = f"signal {-done.returncode}"
        result["error"] = f"killed by {killed}" + (
            ": this PyTorch build uses instructions the CPU does not have" if killed == "SIGILL" else "")
    elif done.returncode:
        result["error"] = (done.stderr.strip().splitlines() or [f"exit status {done.returncode}"])[-1]
    else:
        try:
            result["volts"] = np.array([row[1] for row in json.loads(done.stdout)["samples"]], dtype=np.float64)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            result["error"] = f"unreadable answer: {exc}"
    return result


def measure_latency(generator, name: str, repeats: int) -> dict:
    """One 30 s strip as in Table 1 of the paper: one thread, one warm-up, then `repeats` timed runs."""
    torch = generator.torch
    torch.set_num_threads(1)
    z = seeded_noise(torch, 0)
    inputs = (z,) if name == "lsm" else (z, torch.tensor([generator.condition("gxu_finger", 75.)]))
    times = []
    with torch.inference_mode():
        generator.model(*inputs)
        for _ in range(repeats):
            started = time.perf_counter()
            generator.model(*inputs)
            times.append(1000 * (time.perf_counter() - started))
    return dict(median=statistics.median(times), min=min(times), max=max(times), repeats=repeats,
                threads=torch.get_num_threads())


def check_generator(name: str, entry: dict, tolerance: float, repeats: int, with_worker: bool) -> dict:
    import numpy as np
    label, cases = LABELS[name], entry["cases"]
    section(label)
    out = dict(model_sha256=None, cases=[])
    # The worker goes first: a PyTorch build that kills a process with an illegal instruction
    # would otherwise take this script down before it can report anything.
    if with_worker:
        print("  starting the generator worker ...", flush=True)
    worker = run_worker(name, cases[0]) if with_worker else None
    if worker is not None and worker.get("returncode", 0) < 0:
        out["worker"] = worker
        record("FAIL", f"{label}: generator worker", worker["error"])
        return out

    started = time.perf_counter()
    try:
        generator = load_generator(name)
    except Exception as exc:  # noqa: BLE001 - report whatever the app's loader raises
        record("FAIL", f"{label}: load with the app's loader", f"{type(exc).__name__}: {exc}")
        return out
    out.update(model_sha256=generator.sha256, load_s=time.perf_counter() - started)
    if generator.sha256 != entry["sha256"]:
        record("FAIL", f"{label}: model file", "Its SHA-256 differs from the model the reference was made with. "
               "Deploy the committed assets/neural, or remake the reference on the laptop.")
        return out
    record("PASS", f"{label}: loads, SHA-256 equal to the manifest and the reference",
           f"{out['load_s']:.2f} s to hash and load")

    torch = generator.torch
    problems, condition_differs = [], []
    for case in cases:
        expected = _unpack(case["strip"]).astype(np.float64)
        row = dict(seed=case["seed"], domain=case["domain"], heart_rate=case["heart_rate"])
        try:
            strip = model_strip(generator, _unpack(case["noise"]), case["condition"])
            if not np.isfinite(strip).all() or strip.min() < -1e-6 or strip.max() > 1 + 1e-6:
                raise ValueError("output not finite or outside 0-1")
            if not np.isfinite(expected).all():
                raise ValueError("reference strip not finite")
            row["max_normalized_error"] = float(np.abs(strip - expected).max())
            row["max_abs_error_v"] = IR_AC_V * row["max_normalized_error"]
            # torch.randn rounds differently without AVX2 (the Pi): reported, not judged.
            row["noise_max_abs_diff"] = float(np.abs(seeded_noise(torch, case["seed"])[0].numpy().astype(np.float64)
                                                     - _unpack(case["noise"])).max())
            if case["condition"] is not None and generator.condition(case["domain"], case["heart_rate"]) != case["condition"]:
                condition_differs.append(case["seed"])
            row["app_max_abs_error_v"] = float(np.abs(app_ir_volts(generator, case) - ir_volts(expected)).max())
        except Exception as exc:  # noqa: BLE001 - a failing case must not hide the others
            problems.append(f"seed {case['seed']}: {type(exc).__name__}: {exc}")
        out["cases"].append(row)

    scored = [row for row in out["cases"] if "max_normalized_error" in row]
    worst = max((row["max_normalized_error"] for row in scored), default=None)
    if not scored and not problems:
        problems.append("the reference holds no case for this model")
    if problems:
        record("FAIL", f"{label}: strips from the stored inputs", "\n".join(problems))
    elif worst > tolerance:
        record("FAIL", f"{label}: strips from the stored inputs differ from the laptop's",
               f"max {worst:.2e} (tolerance {tolerance:.0e}) = {IR_AC_V * worst * 1e3:.3f} mV on IR")
    else:
        record("PASS", f"{label}: strips from the stored inputs equal the laptop's within {tolerance:.0e}",
               f"max {worst:.2e} = {IR_AC_V * worst / config.DAC_V_PER_STEP:.4f} DAC steps "
               f"over {len(scored)} strips")

    if condition_differs:
        record("FAIL", f"{label}: the app's condition vectors equal the laptop's",
               f"seeds {condition_differs} differ; check assets/neural/manifest.json")
    if app_rows := [row for row in scored if "app_max_abs_error_v" in row]:
        app_worst = max(row["app_max_abs_error_v"] for row in app_rows)
        noise = max(row["noise_max_abs_diff"] for row in app_rows)
        record("PASS" if app_worst <= IR_AC_V * tolerance else "FAIL",
               f"{label}: the app's generate() returns the laptop strips",
               f"max {app_worst * 1e6:.3f} uV on the infrared channel (tolerance {IR_AC_V * tolerance * 1e6:.0f} uV); "
               f"seeded noise differs from the laptop's by at most {noise:.2e}")

    if worker is not None:
        volts = worker.pop("volts", None)
        out["worker"] = worker
        if volts is None:
            record("FAIL", f"{label}: generator worker", worker["error"])
        else:
            seed = cases[0]["seed"]
            worker["max_abs_error_v"] = float(np.abs(volts - ir_volts(_unpack(cases[0]["strip"]))).max())
            matches = worker["max_abs_error_v"] <= IR_AC_V * tolerance  # False for NaN as well
            record("PASS" if matches else "FAIL",
                   f"{label}: generator worker answered in {worker['seconds']:.1f} s, "
                   f"{100 * worker['seconds'] / WORKER_TIMEOUT_S:.0f}% of the {WORKER_TIMEOUT_S} s "
                   "the Neural page waits",
                   f"python -m core.sequence_worker {seed} --model {name}: "
                   f"max {worker['max_abs_error_v'] * 1e6:.3f} uV from the laptop strip")

    try:
        latency = out["latency_ms"] = measure_latency(generator, name, repeats)
    except Exception as exc:  # noqa: BLE001 - a model that cannot run is reported, not raised
        record("FAIL", f"{label}: timing", f"{type(exc).__name__}: {exc}")
        return out
    print(f"        one 30 s strip: median {latency['median']:.1f} ms (min {latency['min']:.1f}, "
          f"max {latency['max']:.1f}) over {repeats} runs on {latency['threads']} thread")
    return out


# ---------------------------------------------------------------------------
# Reference and report
# ---------------------------------------------------------------------------

def make_reference(path: Path) -> int:
    if platform.machine() == "aarch64":
        print("Make the reference on the laptop that produced the paper's numbers, not on the Pi.")
        return 2
    import torch
    reference = dict(about="Laptop strips for scripts/verify_generators_on_pi.py. Arrays are float32, "
                           "little-endian, base64. Remake with --make-reference when a model changes.",
                     made_with=describe_machine(), models={})
    for name in LABELS:
        generator = load_generator(name)
        prompts = [(seed, None, None) for seed in LSM_SEEDS] if name == "lsm" else CASES
        cases = []
        for seed, domain, rate in prompts:
            noise = seeded_noise(torch, seed)[0].numpy()
            condition = None if name == "lsm" else generator.condition(domain, rate)
            cases.append(dict(seed=seed, domain=domain, heart_rate=rate, condition=condition,
                              noise=_pack(noise), strip=_pack(model_strip(generator, noise, condition))))
        reference["models"][name] = dict(sha256=generator.sha256, cases=cases)
    path.write_text(json.dumps(reference, indent=1) + "\n")
    print(f"Wrote {path}")
    return 0


def _relative(path: Path) -> str:
    path = path.resolve()
    return str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path)


def finish(args, machine: dict, reference: dict | None, generators: dict) -> int:
    counts = {status: sum(r["status"] == status for r in _RESULTS) for status in ("PASS", "FAIL", "SKIP")}
    section("Summary")
    print(f"  {counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped")
    print("  A pass covers the generators' arithmetic on this CPU, not DAC, LED or optical output.")
    if args.out:
        source = dict(file=_relative(args.reference), made_with=(reference or {}).get("made_with"))
        if args.reference.is_file():
            source["sha256"] = hashlib.sha256(args.reference.read_bytes()).hexdigest()
        report = dict(check="scripts/verify_generators_on_pi.py",
                      date_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), machine=machine,
                      reference=source, tolerance_normalized=args.tolerance, ir_mapping_v=[IR_DC_V, IR_AC_V],
                      dac_v_per_step=config.DAC_V_PER_STEP, generators=generators, results=_RESULTS,
                      failed=counts["FAIL"])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1, allow_nan=False) + "\n")
        print(f"  report: {args.out}")
    return 1 if counts["FAIL"] else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check the shipped generators against the laptop reference.")
    parser.add_argument("--out", type=Path, help="write the JSON report to this file")
    parser.add_argument("--reference", type=Path, default=REFERENCE, help="laptop reference (default: %(default)s)")
    parser.add_argument("--models", nargs="+", choices=tuple(LABELS), default=list(LABELS))
    parser.add_argument("--repeats", type=int, default=7, help="timed runs after the warm-up (default: 7)")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE,
                        help="largest accepted difference in normalised units (default: %(default)g)")
    parser.add_argument("--no-worker", action="store_true", help="skip the end-to-end run of the worker process")
    parser.add_argument("--make-reference", action="store_true",
                        help="write the reference from this machine (on the laptop) and exit")
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.make_reference:
        return make_reference(args.reference)

    _RESULTS.clear()
    section("Machine")
    machine = describe_machine()
    board = f" on {machine['board']}" if "board" in machine else ""
    print(f"  {machine['cpu']}{board}, {machine['machine']}, Python {machine['python']}, "
          f"torch {machine['torch']}, numpy {machine['numpy']}")
    pinned, installed = pinned_torch(machine["machine"]), (machine["torch"] or "").split("+")[0]
    if machine["torch"] is None:
        record("FAIL", "torch is installed", "Install requirements/neural.txt into this .venv.")
    elif pinned is None:
        record("FAIL" if machine["machine"] == "aarch64" else "SKIP", "torch version",
               f"requirements/neural.txt pins no torch for {machine['machine']}")
    elif installed == pinned:
        record("PASS", f"torch {installed} is the version requirements/neural.txt pins for {machine['machine']}")
    elif machine["machine"] == "aarch64":
        record("FAIL", f"torch {installed}, but requirements/neural.txt pins {pinned} for {machine['machine']}",
               "torch 2.10 stops with an illegal instruction on the Pi's Cortex-A72.")
    else:
        record("SKIP", f"torch {installed}, but requirements/neural.txt pins {pinned} for {machine['machine']}",
               "The strips below are still judged against the laptop reference.")
    # On the Pi a wrong torch build can kill this process at import, so stop before importing it.
    if machine["torch"] is None or (machine["machine"] == "aarch64" and installed != pinned):
        return finish(args, machine, None, {})
    try:
        reference = json.loads(args.reference.read_text())
        entries = {name: reference["models"][name] for name in args.models}
    except (OSError, ValueError, KeyError) as exc:
        record("FAIL", f"reference {args.reference}", f"{type(exc).__name__}: {exc}")
        return finish(args, machine, None, {})
    generators = {}
    for name, entry in entries.items():
        try:
            generators[name] = check_generator(name, entry, args.tolerance, args.repeats, not args.no_worker)
        except Exception as exc:  # noqa: BLE001 - a malformed reference entry is a FAIL, not a crash
            record("FAIL", f"{LABELS[name]}: reference entry", f"{type(exc).__name__}: {exc}")
            generators[name] = dict(error=f"{type(exc).__name__}: {exc}")
    return finish(args, machine, reference, generators)


if __name__ == "__main__":
    sys.exit(main())
