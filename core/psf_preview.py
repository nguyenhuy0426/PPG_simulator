"""PSF-GAN CPU preview; never accesses the DAC or sensor."""
import hashlib
import json
import math
from pathlib import Path

from core.neural_preview import Preview

DEFAULT_PSF_BUNDLE = Path(__file__).resolve().parents[1]/'assets'/'psf'


class PSFSequenceGenerator:
    def __init__(self, bundle=DEFAULT_PSF_BUNDLE):
        import torch
        self.torch = torch
        torch.set_num_threads(1)
        bundle = Path(bundle)
        self.manifest = json.loads((bundle/'manifest.json').read_text())
        m = self.manifest
        if (m['kind'], m['fs'], m['length'], m['latent'], m['noise_shape'], m['hr_range']) != (
                'psf_gan', 40, 1200, 128, [6, 1600], [40, 180]):
            raise ValueError('Unsupported PSF bundle contract')
        path = bundle/'generator.ts'
        if hashlib.sha256(path.read_bytes()).hexdigest() != m['sha256']:
            raise ValueError('PSF generator checksum mismatch')
        self.model = torch.jit.load(str(path), map_location='cpu').eval()

    def generate(self, seed, heart_rate=75.):
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
            raise ValueError('Seed must be an integer from 0 to 4294967295')
        if not math.isfinite(heart_rate) or not 40 <= heart_rate <= 180:
            raise ValueError('PSF HR target must be 40–180 bpm')
        torch = self.torch
        rng = torch.Generator(device='cpu').manual_seed(seed)
        with torch.inference_mode():
            wave = self.model(torch.randn(1, 128, generator=rng), torch.tensor([float(heart_rate)]),
                              torch.randn(1, 6, 1600, generator=rng))
        if (tuple(wave.shape) != (1, 1200) or not torch.isfinite(wave).all()
                or wave.min() < 0 or wave.max() > 1 or wave.max()-wave.min() < 1e-6):
            raise ValueError('Invalid PSF waveform')
        samples = [(i/40, 1.5+.045*x, 1.5+.0216*x) for i, x in enumerate(wave[0].tolist())]
        return Preview('PSF-GAN', samples, 40, seed, float(heart_rate), None, self.manifest['sha256'],
                       (float(heart_rate),), 'psf_gan_fp32_ft_v1',
                       dict(exploratory=True, paired_ir_red=False, hr_control='requested, not guaranteed',
                            checkpoint_step=self.manifest['checkpoint_step'],
                            preprocessing='MIMIC-III PPG 0.5–8 Hz, min-max, native 30 s at 40 Hz',
                            generation='One generated sequence; no repeated single pulse', clinical_validation=False))
