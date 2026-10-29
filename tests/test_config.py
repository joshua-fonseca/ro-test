import json

from scanner.logic.config import Config, load_config


def test_defaults_when_no_file(tmp_path):
    assert load_config(str(tmp_path / "missing.json")) == Config()
    assert Config().window_width is None and Config().window_height is None  # largest that fits


def test_file_overrides_known_keys_and_ignores_unknown(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"min_window_width": 1300, "window_width": 1600, "bogus": 1}))
    c = load_config(str(p))
    assert (c.min_window_width, c.window_width, c.window_height) == (1300, 1600, None)
