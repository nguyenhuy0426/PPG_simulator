"""Export a trusted PSF release with explicit noise for repeatable CPU inference."""
import argparse
import hashlib
import json
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F

from ml.kaggle_physigpt.pure_gan import load_release, view


class ExportGenerator(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, z, hr, noise):
        model = self.model
        w = model.style(z, hr)
        source, _ = model.excitation(w, hr)
        x = model.stem(w).view(len(z), -1, model.base)
        for i, block in enumerate(model.blocks):
            n = noise[:, i:i+1, :x.shape[-1]*2]
            x = block(x, w, source, n)
        return view(model.out(F.leaky_relu(x, .2))[:, 0], model.mask)


def export(checkpoint, output):
    torch.set_num_threads(1)
    model, state = load_release(checkpoint)
    if not state['hr_cond']:
        raise ValueError('The app requires a heart-rate conditioned PSF release')
    if not all(torch.isfinite(v).all() for v in model.state_dict().values()):
        raise ValueError('Non-finite generator weights')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    wrapper = ExportGenerator(model).eval()
    args = (torch.randn(1, model.latent), torch.tensor([75.]), torch.randn(1, len(model.blocks), 1600))
    with torch.inference_mode():
        rng = torch.Generator().manual_seed(42)
        expected = model.windows(args[0], args[1], rng)
        rng.manual_seed(42)
        noise = torch.zeros_like(args[2])
        for i in range(len(model.blocks)):
            length = model.base*2**(i+1)
            noise[:, i:i+1, :length] = torch.randn(1, 1, length, generator=rng)
        torch.testing.assert_close(wrapper(args[0], args[1], noise), expected, rtol=0, atol=0)
        traced = torch.jit.trace(wrapper, args)
        for hr in (40., 75., 120., 180.):
            values = (torch.randn_like(args[0]), torch.tensor([hr]), torch.randn_like(args[2]))
            a, b = wrapper(*values), traced(*values)
            torch.testing.assert_close(a, b, rtol=2e-5, atol=2e-6)
            assert a.shape == (1, 1200) and torch.isfinite(a).all() and a.min() >= 0 and a.max() <= 1
    path = output/'generator.ts'
    traced.save(str(path))
    metadata = dict(kind='psf_gan', model_file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    checkpoint_sha256=hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
                    checkpoint_step=state['step'], selection=state['select'], fs=40, length=1200,
                    latent=model.latent, noise_shape=[len(model.blocks), 1600], hr_range=[40, 180],
                    torch_export_version=torch.__version__, status='experimental_simulation',
                    paired_ir_red=False, clinical_validation=False)
    (output/'manifest.json').write_text(json.dumps(metadata, indent=2)+'\n')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.checkpoint, args.output)))
