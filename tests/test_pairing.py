"""Phone pairing QR (comm/pairing.py). Run: PPG_DRY_RUN=1 python3 -m pytest tests/test_pairing.py -q"""
import hashlib
import ssl
import subprocess

import pytest

from comm import pairing
from comm.remote_config import MqttSettings


def make_cert(tmp_path):
    """A real PEM produced by openssl when available, so the hash is checked against an independent tool."""
    key, crt = tmp_path / "k.pem", tmp_path / "c.pem"
    try:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                        "-nodes", "-subj", "/CN=ppgsim test", "-days", "1", "-keyout", str(key), "-out", str(crt)],
                       check=True, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("openssl not available")
    return crt


SETTINGS = MqttSettings(device_id="pi4-lab1", host="10.0.0.5", port=8883, tls=True, ca_file="",
                        username="pi4-lab1", password="pi-secret")
PAIR = {"username": "phone1", "password": "app-secret"}


def test_fingerprint_is_sha256_of_der(tmp_path):
    crt = make_cert(tmp_path)
    der = ssl.PEM_cert_to_DER_cert(crt.read_text())
    assert pairing.ca_fingerprint(crt) == hashlib.sha256(der).hexdigest()


def test_full_code_round_trips_and_shares_only_the_app_account(tmp_path):
    crt = make_cert(tmp_path)
    settings = MqttSettings(**{**SETTINGS.__dict__, "ca_file": str(crt)})
    uri = pairing.pairing_uri("MedicalSimulatorRPi", "d8:3a:dd:42:bb:d6", settings, PAIR)
    fields = pairing.parse_pairing_uri(uri)
    assert fields["a"] == "D8:3A:DD:42:BB:D6" and fields["n"] == "MedicalSimulatorRPi"
    assert (fields["d"], fields["h"], fields["p"], fields["t"]) == ("pi4-lab1", "10.0.0.5", "8883", "1")
    assert (fields["u"], fields["k"]) == ("phone1", "app-secret")
    assert len(fields["f"]) == 64
    assert "pi-secret" not in uri                       # the Pi's own broker password never goes in the code
    assert pairing.has_internet(fields)


def test_public_host_override_and_system_ca():
    uri = pairing.pairing_uri("", "", SETTINGS, {**PAIR, "host": "broker.example.org", "port": 443})
    fields = pairing.parse_pairing_uri(uri)
    assert fields["h"] == "broker.example.org" and fields["p"] == "443" and "f" not in fields


def test_bluetooth_only_without_internet_settings_or_app_account():
    for mqtt, pair in ((None, PAIR), (SETTINGS, None), (SETTINGS, {"password": "x"})):
        fields = pairing.parse_pairing_uri(pairing.pairing_uri("Pi", "D8:3A:DD:42:BB:D6", mqtt, pair))
        assert fields["a"] == "D8:3A:DD:42:BB:D6" and not pairing.has_internet(fields)


def test_bad_address_is_left_out():
    fields = pairing.parse_pairing_uri(pairing.pairing_uri("Pi", "not-a-mac"))
    assert "a" not in fields


def test_foreign_codes_are_refused():
    for text in ("https://example.org", "ppgsim://pair?v=9&a=D8:3A:DD:42:BB:D6", "WIFI:S:x;;"):
        with pytest.raises(ValueError):
            pairing.parse_pairing_uri(text)


def test_controller_address_from_bluetoothctl(monkeypatch):
    out = "Controller AA:BB:CC:DD:EE:01 usb\nController d8:3a:dd:42:bb:d6 MedicalSimulatorRPi [default]\n"
    monkeypatch.setattr(pairing.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""))
    assert pairing.local_ble_address() == "D8:3A:DD:42:BB:D6"


def test_missing_bluetoothctl_gives_no_address(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError("bluetoothctl")
    monkeypatch.setattr(pairing.subprocess, "run", boom)
    assert pairing.local_ble_address() == ""


def test_qr_image_is_square_and_decodable_size():
    from ui.pair_dialog import QR_PIXELS, qr_image
    image = qr_image(pairing.pairing_uri("Pi", "D8:3A:DD:42:BB:D6", SETTINGS, PAIR))
    assert image.size[0] == image.size[1] <= QR_PIXELS
