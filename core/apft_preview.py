"""CPU-only APFT-GAN sequence inference for the experimental app mode."""
import hashlib
import json
import math
from pathlib import Path

from core.neural_preview import Preview


class RangeMiss(ValueError):
    """No window's measured HR fell inside the requested range within the time budget."""

    def __init__(self, lo, hi, tries):
        self.lo, self.hi, self.tries = lo, hi, tries
        measured = ', '.join('-' if t[3] is None else f'{t[3]:.1f}' for t in tries)
        super().__init__(f'APFT: no window in {lo:g}-{hi:g} bpm after {len(tries)} tries (measured {measured})')

DEFAULT_APFT_BUNDLE = Path(__file__).resolve().parents[1] / 'assets' / 'apft'


class APFTSequenceGenerator:
    def __init__(self, bundle=DEFAULT_APFT_BUNDLE):
        import torch
        from core import apft_fast
        self.torch = torch
        torch.set_num_threads(1)
        bundle = Path(bundle)
        self.manifest = json.loads((bundle / 'manifest.json').read_text())
        m = self.manifest
        if (m['kind'], m['config'], m['hr_cond'], m['fs'], m['length'], m['steps']) != (
                'apft_gan', 'large', True, 40, 1200, 16):
            raise ValueError('Unsupported APFT bundle contract')
        path = bundle / 'generator.pt'
        if hashlib.sha256(path.read_bytes()).hexdigest() != m['sha256']:
            raise ValueError('APFT generator checksum mismatch')
        # Same weights and samples as build(torch.load(...)), faster on the Pi 4 (core/apft_fast.py): no random init
        # of the 100 M parameters before they are overwritten (10.2 -> 6.6 s), and the flow head's (h, t) terms
        # computed once per patch (94.8 -> 45.7 s per window, identical output).
        self.model = apft_fast.fast(apft_fast.load(path, mmap=False))

    def window(self, seed, heart_rate=75.):
        """One validated 30 s, 40 Hz min-max window as 1200 floats."""
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
            raise ValueError('Seed must be an integer from 0 to 4294967295')
        if not math.isfinite(heart_rate) or not 40 <= heart_rate <= 180:
            raise ValueError('APFT HR target must be 40–180 bpm')
        torch = self.torch
        with torch.inference_mode():
            wave = self.model.generate(1, steps=16, seed=seed, hr=float(heart_rate))
        if (tuple(wave.shape) != (1, 1200) or not torch.isfinite(wave).all()
                or wave.min() < 0 or wave.max() > 1 or wave.max() - wave.min() < 1e-6):
            raise ValueError('Invalid APFT waveform')
        return wave[0].tolist()

    def _preview(self, window, seed, heart_rate, **extra):
        samples = [(i / 40, 1.5 + .045 * x, 1.5 + .0216 * x) for i, x in enumerate(window)]
        return Preview('APFT-GAN', samples, 40, seed, float(heart_rate), None,
                       self.manifest['sha256'], (float(heart_rate),), 'apft_gan_v3_hr_v1',
                       {**dict(exploratory=True, paired_ir_red=False, hr_control='requested, not guaranteed',
                               checkpoint_step=self.manifest['checkpoint_step'], clinical_validation=False,
                               generation='30 autoregressive patches, 40 samples each; 16-step Heun flow head',
                               preprocessing='MIMIC-III PPG 0.5–8 Hz, min-max, 30 s at 40 Hz'), **extra})

    def generate(self, seed, heart_rate=75.):
        return self._preview(self.window(seed, heart_rate), seed, heart_rate)

    def windows(self, seed, heart_rates):
        """Validated min-max windows, one per requested HR, from one batched generator call (seed drives the batch)."""
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
            raise ValueError('Seed must be an integer from 0 to 4294967295')
        if not heart_rates or not all(math.isfinite(h) and 40 <= h <= 180 for h in heart_rates):
            raise ValueError('APFT HR targets must be 40–180 bpm')
        torch = self.torch
        with torch.inference_mode():
            waves = self.model.generate(len(heart_rates), steps=16, seed=seed,
                                        hr=torch.tensor([float(h) for h in heart_rates]))
        if (tuple(waves.shape) != (len(heart_rates), 1200) or not torch.isfinite(waves).all()
                or waves.min() < 0 or waves.max() > 1):
            raise ValueError('Invalid APFT waveform')
        return [w.tolist() for w in waves]

    def generate_in_range(self, seed, lo, hi, budget_s=None):
        """A window whose measured beat rate lies in [lo, hi] bpm (core/apft_range.py), or RangeMiss."""
        from core import apft_range
        result = apft_range.search(self.windows, lo, hi, seed,
                                   apft_range.DEFAULT_BUDGET_S if budget_s is None else budget_s)
        if result.window is None:
            raise RangeMiss(float(lo), float(hi), result.tries)
        return self._preview(result.window, result.seed, result.request, hr_range=[float(lo), float(hi)],
                             hr_measured_bpm=round(result.check.bpm, 2), hr_beats=result.check.beats,
                             batch_index=result.index, batch=apft_range.BATCH, tries=result.tries,
                             hr_control='measured beat rate inside the requested range')
