import json

from ui.i18n import LANGUAGES, LANGUAGE_EN, LANGUAGE_VI, normalise_language, text


def test_languages_have_stable_labels_and_shell_translations():
    assert LANGUAGES == {"en": "English", "vi": "Tiếng Việt"}
    assert text(LANGUAGE_EN, "classic") != text(LANGUAGE_VI, "classic")
    assert text(LANGUAGE_VI, "language") == "Ngôn ngữ"
    assert text(LANGUAGE_EN, "missing_key") == "missing_key"


def test_invalid_persisted_language_falls_back_to_english():
    assert normalise_language(None) == LANGUAGE_EN
    assert normalise_language("fr") == LANGUAGE_EN
    assert normalise_language(LANGUAGE_VI) == LANGUAGE_VI


def test_config_load_normalises_language(monkeypatch, tmp_path):
    import config_store
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_store, "CONFIG_JSON_PATH", str(path))
    path.write_text(json.dumps({"language": "vi", "heart_rate": 82}))
    assert config_store.load_config()["language"] == "vi"
    path.write_text(json.dumps({"language": "invalid"}))
    assert config_store.load_config()["language"] == "en"
