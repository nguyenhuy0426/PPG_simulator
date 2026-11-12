"""Real released APFT model: waveform/seed contract and corrupt artifact rejection."""
import json
import math
from pathlib import Path

import pytest

from core.apft_preview import APFTSequenceGenerator, DEFAULT_APFT_BUNDLE


@pytest.mark.skipif(not (DEFAULT_APFT_BUNDLE / 'generator.pt').exists(), reason='Optional APFT bundle absent')
def test_released_waveform_and_seed_contract(tmp_path):
    backend = APFTSequenceGenerator()
    first = backend.generate(42, 75)
    second = backend.generate(42, 75)
    assert first.samples == second.samples
    assert len(first.samples) == 1200 and first.native_fs == 40
    assert first.hr_target == 75 and first.name == 'APFT-GAN'
    assert first.samples[-1][0] == 1199 / 40
    assert all(math.isfinite(v) for row in first.samples for v in row)
    assert first.provenance['paired_ir_red'] is False
    for seed, hr in ((True, 75), (-1, 75), (2**32, 75), (42, float('nan')), (42, 39), (42, 181)):
        with pytest.raises(ValueError):
            backend.generate(seed, hr)
    (tmp_path / 'manifest.json').write_text((DEFAULT_APFT_BUNDLE / 'manifest.json').read_text())
    (tmp_path / 'generator.pt').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='checksum'):
        APFTSequenceGenerator(tmp_path)
