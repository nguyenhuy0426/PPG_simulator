"""scripts/verify_generators_on_pi.py on the laptop: it passes against the committed reference and
fails when the reference and the models disagree. No hardware; the end-to-end tests need torch."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_generators_on_pi.py"


def _load_check():
    spec = importlib.util.spec_from_file_location("verify_generators_on_pi", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load_check()


def _run(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True,
                          timeout=600, env=None if env is None else {**os.environ, **env})


def _changed_reference(tmp_path, delta):
    """The committed reference with one PhysioMix sample moved by `delta` normalised units."""
    reference = json.loads(check.REFERENCE.read_text())
    case = reference["models"]["physiomix"]["cases"][2]
    strip = check._unpack(case["strip"]).copy()
    strip[600] += delta
    case["strip"] = check._pack(strip)
    changed = tmp_path / "reference.json"
    changed.write_text(json.dumps(reference))
    return changed


def test_torch_pin_is_read_per_architecture(tmp_path):
    pinned = tmp_path / "neural.txt"
    pinned.write_text("numpy>=1.26,<3\n"
                      "torch==2.10.0; platform_machine != 'aarch64'\n"
                      "torch==2.5.1; platform_machine == 'aarch64'\n")
    assert check.pinned_torch("aarch64", pinned) == "2.5.1"
    assert check.pinned_torch("x86_64", pinned) == "2.10.0"
    loose = tmp_path / "loose.txt"
    loose.write_text("torch>=2.5,<3\n")
    assert check.pinned_torch("aarch64", loose) is None


def test_reference_belongs_to_the_shipped_models():
    """A model replaced without remaking the reference would make every Pi check fail."""
    reference = json.loads(check.REFERENCE.read_text())
    manifest = json.loads((ROOT / "assets" / "neural" / "manifest.json").read_text())["models"]
    for name, key in (("physiomix", "physiomix_generator"), ("physioflow", "physioflow_generator"),
                      ("lsm", "lsm_generator")):
        assert reference["models"][name]["sha256"] == manifest[key]["sha256"]
        for case in reference["models"][name]["cases"]:
            assert len(check._unpack(case["noise"])) == len(check._unpack(case["strip"])) == 1200


@pytest.fixture(scope="module")
def laptop(tmp_path_factory):
    pytest.importorskip("torch")
    report = tmp_path_factory.mktemp("generators") / "report.json"
    done = _run("--repeats", "1", "--out", str(report))
    assert report.is_file(), done.stdout[-4000:] + done.stderr[-2000:]
    return done, json.loads(report.read_text())


def test_laptop_reproduces_its_own_reference(laptop):
    done, report = laptop
    assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-2000:]
    assert report["failed"] == 0
    labels = [result["label"] for result in report["results"] if result["status"] == "PASS"]
    for label in ("PhysioMix", "PhysioFlow", "LSM-GAN"):  # every check ran, not only those recorded
        for check_name in ("SHA-256", "strips from the stored inputs", "generate()", "generator worker"):
            assert any(text.startswith(label) and check_name in text for text in labels), (label, check_name)
    for name in ("physiomix", "physioflow", "lsm"):
        generator = report["generators"][name]
        assert all(case["max_normalized_error"] <= report["tolerance_normalized"]
                   and case["app_max_abs_error_v"] <= check.IR_AC_V * report["tolerance_normalized"]
                   for case in generator["cases"])
        assert generator["worker"]["max_abs_error_v"] <= check.IR_AC_V * report["tolerance_normalized"]
        assert 0 < generator["worker"]["seconds"] < generator["worker"]["timeout_s"]
        assert generator["latency_ms"]["threads"] == 1 and generator["latency_ms"]["repeats"] == 1


def test_a_changed_reference_strip_fails(tmp_path):
    pytest.importorskip("torch")
    changed = _changed_reference(tmp_path, .01)  # 0.45 mV at the default amplitude: ten times the tolerance
    done = _run("--reference", str(changed), "--models", "physiomix", "--no-worker", "--repeats", "1")
    assert done.returncode == 1
    assert "[FAIL] PhysioMix: strips from the stored inputs differ from the laptop's" in done.stdout
    assert "[FAIL] PhysioMix: the app's generate() returns the laptop strips" in done.stdout


def test_a_difference_below_the_tolerance_passes(tmp_path):
    pytest.importorskip("torch")
    changed = _changed_reference(tmp_path, 5e-4)
    done = _run("--reference", str(changed), "--models", "physiomix", "--no-worker", "--repeats", "1")
    assert done.returncode == 0, done.stdout[-4000:]


def test_scalar_randn_still_passes(tmp_path):
    """Without AVX2 (the Pi), torch.randn rounds the seeded noise differently; the strips must still pass."""
    pytest.importorskip("torch")
    report = tmp_path / "report.json"
    done = _run("--models", "physiomix", "--no-worker", "--repeats", "1", "--out", str(report),
                env={"ATEN_CPU_CAPABILITY": "default"})
    assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-2000:]
    assert "[PASS] PhysioMix: the app's generate() returns the laptop strips" in done.stdout
    assert 0 < max(case["noise_max_abs_diff"] for case in json.loads(report.read_text())["generators"]
                   ["physiomix"]["cases"]) < 1e-5


def test_the_reference_is_not_made_on_the_pi(tmp_path, monkeypatch):
    monkeypatch.setattr(check.platform, "machine", lambda: "aarch64")
    target = tmp_path / "reference.json"
    assert check.main(["--make-reference", "--reference", str(target)]) == 2
    assert not target.exists()


def test_no_torch_pin_on_the_pi_fails(monkeypatch):
    """Without a pin the script cannot tell a safe build, checks nothing and must not exit 0."""
    monkeypatch.setattr(check.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(check, "pinned_torch", lambda machine: None)
    assert check.main(["--no-worker"]) == 1
