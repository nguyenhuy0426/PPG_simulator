"""CPU-only APFT-GAN sequence inference for the experimental app mode."""
import hashlib
import json
import math
from pathlib import Path

from core.neural_preview import Preview

DEFAULT_APFT_BUNDLE = Path(__file__).resolve().parents[1] / 'assets' / 'apft'


class APFTSequenceGenerator:
    def __init__(self, bundle=DEFAULT_APFT_BUNDLE):
        import torch
        from core.apft_network import build
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
        self.model = build(torch.load(path, map_location='cpu', weights_only=True)).eval()

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

    def generate(self, seed, heart_rate=75.):
        samples = [(i / 40, 1.5 + .045 * x, 1.5 + .0216 * x) for i, x in enumerate(self.window(seed, heart_rate))]
        return Preview('APFT-GAN', samples, 40, seed, float(heart_rate), None,
                       self.manifest['sha256'], (float(heart_rate),), 'apft_gan_v3_hr_v1',
                       dict(exploratory=True, paired_ir_red=False, hr_control='requested, not guaranteed',
                            checkpoint_step=self.manifest['checkpoint_step'], clinical_validation=False,
                            generation='30 autoregressive patches, 40 samples each; 16-step Heun flow head',
                            preprocessing='MIMIC-III PPG 0.5–8 Hz, min-max, 30 s at 40 Hz'))
