"""Reference provenance and interpolation must not imply measured optical pairs."""
import json

import numpy as np
import pytest

from core.neural_preview import reference_preview, export_preview, GAUSSIAN_PROFILE_FILE
from ml.morphology_audit import describe


@pytest.mark.parametrize('profile',['No notch','With notch'])
def test_reference_render_matches_frozen_real_shape(profile,tmp_path):
    row=json.loads(GAUSSIAN_PROFILE_FILE.read_text())['profiles'][profile]
    preview=reference_preview(75,profile)
    values=np.asarray(preview.samples)
    expected=np.interp((values[:,0]*75/60)%1,np.linspace(0,1,256),row['reference_waveform'])
    np.testing.assert_allclose(values[:,1],1.5+.045*expected,atol=1e-14)
    np.testing.assert_allclose(values[:,2],1.5+.0216*expected,atol=1e-14)
    assert preview.provenance['train_exemplar_index']==row['train_exemplar_index']
    path=tmp_path/'reference.csv'
    export_preview(preview,path)
    meta=json.loads(path.with_suffix('.json').read_text())
    assert meta['provenance']['paired_ir_red'] is False
    assert meta['provenance']['independent_validation'] is False
    assert len(values)==3000


@pytest.mark.parametrize('hr',[float('nan'),float('inf'),39,181])
def test_reference_rejects_invalid_hr(hr):
    with pytest.raises(ValueError):
        reference_preview(hr)


def test_reference_requires_exemplar_not_population_mean():
    with pytest.raises(ValueError):
        reference_preview(profile='Balanced')


def test_fwhm_interpolation_on_triangle_and_hr_scaling():
    phase=np.linspace(0,1,256)
    pulse=1-abs(2*phase-1)
    result=describe(pulse,60)
    assert result['fwhm_phase']==pytest.approx(.50196,abs=1e-5)
    assert result['fwhm_ms']==pytest.approx(501.96,abs=.01)
    assert describe(pulse,120)['fwhm_ms']==pytest.approx(result['fwhm_ms']/2)
