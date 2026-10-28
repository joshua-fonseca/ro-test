import json

from config import Config, load_config


def test_defaults_when_no_file(tmp_path):
    assert load_config(str(tmp_path / "missing.json")) == Config()
    assert Config().initial_backward_seconds == 2.0 and Config().cycle_delay_seconds == 15.0


def test_file_overrides_known_keys_and_ignores_unknown(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"initial_backward_seconds": 2.5, "window_width": 1600, "bogus": 1}))
    c = load_config(str(p))
    assert (c.initial_backward_seconds, c.window_width, c.window_height) == (2.5, 1600, 720)
