"""
Tests for config.json / state.json (load, merge-with-defaults, save) and
the rapidfuzz/difflib fallback. Every call takes `app_dir` explicitly, so
these run against pytest's own tmp_path — never the real repo.
"""
import json
import os


def test_load_config_creates_default_file_when_missing(core_module, app_dir):
    config = core_module.load_config(app_dir)
    assert config["match_threshold"] == core_module.DEFAULT_CONFIG["match_threshold"]

    path = os.path.join(app_dir, core_module.CONFIG_FILENAME)
    assert os.path.exists(path)


def test_load_config_merges_partial_or_old_config(core_module, app_dir):
    path = os.path.join(app_dir, core_module.CONFIG_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"match_threshold": 0.42}, f)

    config = core_module.load_config(app_dir)
    assert config["match_threshold"] == 0.42
    assert config["mesh_prefixes"] == core_module.DEFAULT_CONFIG["mesh_prefixes"]


def test_load_config_falls_back_to_default_on_corrupt_json(core_module, app_dir):
    path = os.path.join(app_dir, core_module.CONFIG_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ not valid json")

    config = core_module.load_config(app_dir)
    assert config == core_module.DEFAULT_CONFIG


def test_state_round_trip(core_module, app_dir):
    state = {"last_threshold": 0.77, "last_match_mode": "material_id", "language": "es"}
    core_module.save_state(app_dir, state)
    assert core_module.load_state(app_dir) == state


def test_load_state_returns_empty_dict_when_missing(core_module, app_dir):
    assert core_module.load_state(app_dir) == {}


def test_ensure_rapidfuzz_never_raises_and_never_touches_subprocess(core_module):
    fuzz, has_it = core_module.ensure_rapidfuzz()
    assert has_it in (True, False)
    if not has_it:
        assert fuzz is None
    assert not hasattr(core_module, "subprocess")


def test_get_logger_is_scoped_per_app_dir(core_module, tmp_path):
    dir_a = str(tmp_path / "a")
    dir_b = str(tmp_path / "b")
    os.makedirs(dir_a)
    os.makedirs(dir_b)

    logger_a = core_module.get_logger(dir_a)
    logger_b = core_module.get_logger(dir_b)
    assert logger_a is not logger_b

    logger_a.info("hello from a")
    log_path_a = os.path.join(dir_a, core_module.LOG_FILENAME)
    log_path_b = os.path.join(dir_b, core_module.LOG_FILENAME)
    assert os.path.exists(log_path_a)
    assert not os.path.exists(log_path_b)
