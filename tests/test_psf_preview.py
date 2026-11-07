"""Runtime contract tests; fixture waves are synthetic, not trained-model quality evidence."""
import hashlib
import json
import pytest
import torch
from core.psf_preview import PSFSequenceGenerator
from core.waveform_clip import WaveformClip


class FixtureGenerator(torch.nn.Module):
    def forward(self, z, hr, noise):
        t = torch.arange(1200)/40
        return .5+.4*torch.sin(t[None]*hr[:, None]/60*6.283185+z[:, :1])+.01*noise[:, 0, :1200].tanh()


@pytest.fixture
def bundle(tmp_path):
    args=(torch.randn(1,128),torch.tensor([75.]),torch.randn(1,6,1600))
    torch.jit.trace(FixtureGenerator(),args).save(str(tmp_path/'generator.ts'))
    data=dict(kind='psf_gan',fs=40,length=1200,latent=128,noise_shape=[6,1600],hr_range=[40,180],
              checkpoint_step=500,sha256=hashlib.sha256((tmp_path/'generator.ts').read_bytes()).hexdigest())
    (tmp_path/'manifest.json').write_text(json.dumps(data))
    return tmp_path


def test_repeatable_native_sequence_and_clip_contract(bundle):
    model=PSFSequenceGenerator(bundle)
    a=model.generate(42,75)
    assert a==model.generate(42,75) and a.samples!=model.generate(43,75).samples
    assert len(a.samples)==1200 and a.samples[-1][0]==29.975 and a.native_fs==40
    assert a.hr_target==75 and not a.provenance['paired_ir_red'] and not a.provenance['clinical_validation']
    clip=WaveformClip.from_preview(a)
    clip.validate()
    assert clip.duration==30
    assert model.generate(42,120).samples!=a.samples


@pytest.mark.parametrize('seed,hr',[(True,75),(-1,75),(2**32,75),(1,float('nan')),(1,39),(1,181)])
def test_invalid_requests_rejected(bundle,seed,hr):
    with pytest.raises(ValueError): PSFSequenceGenerator(bundle).generate(seed,hr)


def test_tampered_bundle_is_rejected(bundle):
    with (bundle/'generator.ts').open('ab') as f: f.write(b'bad')
    with pytest.raises(ValueError,match='checksum'): PSFSequenceGenerator(bundle)
