"""Optional CPU inference for the Neural preview page. No signal-engine or DAC I/O."""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path


DEFAULT_BUNDLE = Path(__file__).resolve().parents[1] / "assets" / "neural"
PREVIEW_MODES = ("Gaussian (original)", "cWGAN-GP", "LSM-GAN", "TCN-FiLM")
PREVIEW_MODES += ("Gaussian (fitted)",)
GAUSSIAN_PROFILES = ("Balanced", "No notch", "With notch")
GAUSSIAN_PROFILE_FILE = Path(__file__).resolve().parents[1] / "assets/gaussian/profiles.json"


@dataclass
class Preview:
    name: str
    samples: list
    native_fs: int
    seed: int | None
    hr_target: float | None
    discriminator_score: float | None
    model_sha256: str
    condition: tuple | None
    variant: str
    provenance: dict | None = None


def gaussian_preview(heart_rate=75, profile="Original"):
    """The existing three-Gaussian shaper, with no torch or hardware dependency."""
    from models.waveform import PulseMorphology, PulseShaper, WAVE_PPG
    if not math.isfinite(heart_rate) or not 40 <= heart_rate <= 180:
        raise ValueError("Preview HR target must be 40–180 bpm")
    profile_bytes = b""
    morphology = PulseMorphology()
    if profile != "Original":
        if profile not in GAUSSIAN_PROFILES:
            raise ValueError("Unknown Gaussian profile")
        profile_bytes = GAUSSIAN_PROFILE_FILE.read_bytes()
        parameters = json.loads(profile_bytes)["profiles"][profile]["morphology"]
        morphology = PulseMorphology(**parameters)
    shaper = PulseShaper(morphology)
    samples = []
    for i in range(3000):
        x = shaper.sample(WAVE_PPG, (i / 100 * heart_rate / 60) % 1)
        samples.append((i / 100, 1.5 + .045 * x, 1.5 + .0216 * x))
    source = Path(__file__).resolve().parents[1] / "models/waveform.py"
    return Preview("Gaussian (original)" if profile == "Original" else "Gaussian (fitted)",
                   samples, 100, None, heart_rate, None,
                   hashlib.sha256(source.read_bytes()+profile_bytes).hexdigest(), None,
                   "existing_gaussian_preset" if profile == "Original" else "train_fit_"+profile)


def reference_preview(heart_rate=75, profile="With notch"):
    """Repeat a processed TRAIN exemplar in nominal volts; no hardware access."""
    if not math.isfinite(heart_rate) or not 40 <= heart_rate <= 180:
        raise ValueError("Preview HR target must be 40–180 bpm")
    if profile not in ("No notch", "With notch"):
        raise ValueError("Reference needs a real exemplar profile")
    raw = GAUSSIAN_PROFILE_FILE.read_bytes()
    data = json.loads(raw)
    entry = data["profiles"][profile]
    values = entry["reference_waveform"]
    if (len(values) != 256 or not all(math.isfinite(v) and 0 <= v <= 1.000001 for v in values)
            or max(values)-min(values) < 1e-8):
        raise ValueError("Invalid train reference waveform")
    samples = []
    for i in range(3000):
        phase = ((i/100*heart_rate/60) % 1)*255
        left = int(phase)
        fraction = phase-left
        y = values[left]*(1-fraction)+values[min(left+1,255)]*fraction
        samples.append((i/100,1.5+.045*y,1.5+.0216*y))
    return Preview("Real reference", samples,100,None,heart_rate,None,
                   hashlib.sha256(raw).hexdigest(),None,"train_reference_"+profile,
                   dict(prepared_sha256=data['prepared_sha256'],
                        train_exemplar_index=entry['train_exemplar_index'],
                        source_sample_rate_hz=125, rendered_sample_rate_hz=100,
                        preprocessing="12 Hz lowpass; foot baseline; 256-point phase resampling",
                        transformation="Repeated train pulse; time-scaled to requested HR; nominal IR/RED voltages",
                        independent_validation=False, paired_ir_red=False))


class NeuralPreview:
    """Loaded once by the UI worker; optional dependencies stay off the startup path."""

    def __init__(self, bundle=DEFAULT_BUNDLE):
        try:
            import numpy as np
            import torch
        except ImportError as exc:
            raise RuntimeError("Neural preview needs requirements/neural.txt in the app environment.") from exc
        self.np, self.torch = np, torch
        bundle = Path(bundle)
        try:
            self.manifest = json.loads((bundle / "manifest.json").read_text())
        except OSError as exc:
            raise RuntimeError("Neural models missing. Run scripts/prepare_neural_preview.py first.") from exc
        torch.set_num_threads(1)
        self.models = {}
        for name in ("cwgan_generator", "lsm_generator", "lsm_discriminator", "tcn_generator", "tcn_critic"):
            if name not in self.manifest["models"]:
                raise RuntimeError("Update the model bundle with scripts/prepare_neural_preview.py (TCN required).")
            entry = self.manifest["models"][name]
            path = bundle / entry["file"]
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except FileNotFoundError as exc:
                raise RuntimeError("Neural models missing. Run scripts/prepare_neural_preview.py first.") from exc
            if digest != entry["sha256"]:
                raise ValueError(f"Model checksum mismatch: {name}")
            self.models[name] = torch.jit.load(str(path), map_location="cpu").eval()
        self.condition = np.asarray(self.manifest["cwgan_condition"], dtype=np.float32)
        if self.condition.shape != (7,) or not np.isfinite(self.condition).all():
            raise ValueError("Invalid cWGAN condition in model bundle")

    def generate(self, seed=42, heart_rate=75, morphology="No notch", gaussian_profile="Balanced"):
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
            raise ValueError("Seed must be an integer from 0 to 4294967295")
        if not math.isfinite(heart_rate) or not 40 <= heart_rate <= 180:
            raise ValueError("Pulse HR target must be 40–180 bpm")
        np, torch = self.np, self.torch
        rng = torch.Generator(device="cpu").manual_seed(seed)
        if morphology not in self.manifest["condition_presets"]:
            raise ValueError("Choose With notch or No notch")
        condition = np.asarray(self.manifest["condition_presets"][morphology], dtype=np.float32).copy()
        condition[0] = heart_rate / 200
        with torch.inference_mode():
            pulse = self.models["cwgan_generator"](
                torch.randn(1, 32, generator=rng), torch.tensor(condition[None])).numpy()
            strip = self.models["lsm_generator"](torch.randn(1, 1200, generator=rng))
            scores = self.models["lsm_discriminator"](strip).numpy()
            tcn_rng = torch.Generator(device="cpu").manual_seed(seed)
            tcn = self.models["tcn_generator"](
                torch.randn(1, 32, generator=tcn_rng), torch.tensor(condition[None]))
            tcn_score, _ = self.models["tcn_critic"](tcn, torch.tensor(condition[None]))
            tcn = tcn.numpy()
        if pulse.shape != (1, 256) or tcn.shape != (1, 256) or tuple(strip.shape) != (1, 1, 1200) or scores.shape != (1, 2):
            raise ValueError("Unexpected exported G/D output shape")
        strip = strip.numpy()[0, 0]
        if not all(np.isfinite(x).all() for x in (pulse, strip, scores, tcn, tcn_score.numpy())):
            raise ValueError("Nonfinite neural output")
        if min(pulse.min(), strip.min(), tcn.min()) < -1e-6 or max(pulse.max(), strip.max(), tcn.max()) > 1.000001:
            raise ValueError("Neural output is outside the normalized amplitude range")
        # Phase grid is not a sample rate. Repeat the cWGAN pulse at the requested
        # HR on a 100 Hz clock. LSM retains its native 40 Hz / 30 s timing.
        t = np.arange(3000) / 100
        periodic = np.interp((t * heart_rate / 60) % 1, np.linspace(0, 1, 256), pulse[0])
        tcn_periodic = np.interp((t * heart_rate / 60) % 1, np.linspace(0, 1, 256), tcn[0])
        result = {PREVIEW_MODES[0]: gaussian_preview(heart_rate)}
        for name, shape, fs, hr, score, key, variant in (
            ("cWGAN-GP", periodic, 100, heart_rate, None, "cwgan_generator", "cwgan_pilot_v1"),
            ("LSM-GAN", strip, 40, None, float(scores.mean()), "lsm_generator", self.manifest["lsm_variant"]),
            ("TCN-FiLM", tcn_periodic, 100, heart_rate, float(tcn_score.item()), "tcn_generator", "tcn_film_projection"),
        ):
            samples = [(i / fs, 1.5 + .045 * float(x), 1.5 + .0216 * float(x))
                       for i, x in enumerate(shape)]
            result[name] = Preview(name, samples, fs, seed, hr, score,
                                   self.manifest["models"][key]["sha256"],
                                   tuple(float(x) for x in condition) if hr is not None else None,
                                   variant)
        result["Gaussian (fitted)"] = gaussian_preview(heart_rate, gaussian_profile)
        return result


def export_preview(preview, path, *, dc_v=1.5, ac_ir_v=.045, ac_red_v=.0216):
    """Export native timestamps and explicit nominal calibration, never DAC codes."""
    import csv
    path = Path(path)
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("time_s", "ir_v", "red_v"))
        writer.writerows(preview.samples)
    metadata = dict(model=preview.name, model_sha256=preview.model_sha256,
                    variant=preview.variant, condition=preview.condition,
                    native_fs_hz=preview.native_fs, duration_s=30, seed=preview.seed,
                    hr_target=preview.hr_target, discriminator_score=preview.discriminator_score,
                    dc_v=dc_v, ac_ir_v=ac_ir_v, ac_red_v=ac_red_v, same_shape_both_channels=True,
                    nominal_spo2_target=98, calibration_a=110, calibration_b=25,
                    provenance=preview.provenance,
                    note="Waveform CSV export; no added output filter; not measured SpO2; export does not drive DAC. "
                         "LSM has no HR/notch control. cWGAN critic weights were not saved. "
                         "TCN critic is an unbounded diagnostic score. Gaussian variant identifies original or train-fitted preset. "
                         "Real reference is a processed, time-scaled and repeated train exemplar, not raw paired IR/RED.")
    path.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")


class LSMSequenceGenerator:
    """Only load the chosen sequence GAN on Pi; inference stays off the DAC thread."""
    def __init__(self, bundle=DEFAULT_BUNDLE):
        import torch
        self.torch = torch
        torch.set_num_threads(1)
        bundle = Path(bundle)
        self.manifest = json.loads((bundle / 'manifest.json').read_text())
        entry = self.manifest['models']['lsm_generator']
        path = bundle / entry['file']
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('LSM generator checksum mismatch')
        self.sha256 = entry['sha256']
        self.model = torch.jit.load(str(path), map_location='cpu').eval()

    def generate(self, seed):
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
            raise ValueError('Seed must be an integer from 0 to 4294967295')
        torch = self.torch
        rng = torch.Generator(device='cpu').manual_seed(seed)
        with torch.inference_mode():
            wave = self.model(torch.randn(1,1200,generator=rng))
        if tuple(wave.shape) != (1,1,1200) or not torch.isfinite(wave).all():
            raise ValueError('Invalid LSM output')
        if wave.min() < 0 or wave.max() > 1 or wave.max()-wave.min() < 1e-6:
            raise ValueError('Flat or out-of-range LSM output')
        samples = [(i/40,1.5+.045*x,1.5+.0216*x) for i,x in enumerate(wave[0,0].tolist())]
        return Preview('LSM-GAN',samples,40,seed,None,None,self.sha256,None,
                       self.manifest['lsm_variant'],
                       dict(exploratory=True, paired_ir_red=False,
                            generation='One native 30-second sequence; no repeated single pulse',
                            preprocessing='BIDMC 0.9–5 Hz; whole-window normalization',
                            hr_control=False, diagnosis_labels=False))


def sequence_reference_preview(bundle=DEFAULT_BUNDLE):
    """One real processed training strip; native timing, never pulse repetition."""
    path=Path(bundle)/'real_train_strip.json'
    raw=path.read_bytes()
    data=json.loads(raw)
    wave=data.pop('waveform')
    if data['split']!='train' or data['native_fs_hz']!=40 or len(wave)!=1200 or not all(
            math.isfinite(x) and 0<=x<=1.000001 for x in wave):
        raise ValueError('Invalid real training strip')
    return Preview('Real sequence',[(i/40,1.5+.045*x,1.5+.0216*x) for i,x in enumerate(wave)],
                   40,None,None,None,hashlib.sha256(raw).hexdigest(),None,'real_train_30s',
                   dict(**data,paired_ir_red=False,independent_validation=False))
