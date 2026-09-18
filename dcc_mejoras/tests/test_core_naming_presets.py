"""
Tests for naming presets: named suffix conventions picked from the UI,
and the end-of-name ("suffixes") classification they use.
"""
import json
import os


def _short(core_module):
    return core_module.apply_naming_preset(core_module.DEFAULT_CONFIG, "short_suffixes")


def test_default_preset_is_the_top_level_config(core_module):
    config = dict(core_module.DEFAULT_CONFIG, map_types=[{"id": "baseColor", "match": ["_tint"]}])
    effective = core_module.apply_naming_preset(config, "default")
    assert effective["naming_preset"] == "default"
    assert [mt["id"] for mt in effective["map_types"]] == ["baseColor"]
    assert effective["map_types"][0]["match"] == ["_tint"]
    assert effective["suffix_strip_list"] == config["suffix_strip_list"]


def test_unknown_preset_falls_back_to_default_with_a_warning(core_module):
    warnings = []
    effective = core_module.apply_naming_preset(
        core_module.DEFAULT_CONFIG, "does_not_exist", warn_fn=warnings.append)
    assert effective["naming_preset"] == "default"
    assert len(warnings) == 1 and "does_not_exist" in warnings[0]


def test_preset_fills_color_space_defaults_and_derives_strip_list(core_module):
    effective = _short(core_module)
    by_id = {mt["id"]: mt for mt in effective["map_types"]}
    assert (by_id["baseColor"]["color_space"], by_id["baseColor"]["raw"]) == ("sRGB", False)
    assert (by_id["roughness"]["color_space"], by_id["roughness"]["raw"]) == ("Raw", True)
    assert "BC" in effective["suffix_strip_list"]
    assert "R" in effective["suffix_strip_list"]


def test_short_suffixes_are_matched_at_the_end_of_the_name_only(core_module):
    map_types = _short(core_module)["map_types"]
    classify = core_module.classify_map_type
    assert classify("/t/Rock_R.png", map_types) == "roughness"
    assert classify("/t/Rock_BC_4k.png", map_types) == "baseColor"
    assert classify("/t/Rock_N.1001.png", map_types) == "normal"
    # contains "_R" and "_M" in the middle, but ends with BC
    assert classify("/t/Car_Rim_Metal_BC.png", map_types) == "baseColor"
    assert classify("/t/Rock_Curvature.png", map_types) is None


def test_short_suffixes_example_still_reads_a_standard_substance_export(core_module):
    """Real case: picking the example preset for a regular export
    (Modelado2_Cabeza_BaseColor.png, _Metalness, _Normal...) turned every
    map but Emissive / Height into "no match"."""
    map_types = _short(core_module)["map_types"]
    expected = {"BaseColor": "baseColor", "Normal": "normal", "Roughness": "roughness",
                "Metalness": "metallic", "Emissive": "emission", "Height": "displacement"}
    for suffix, channel in expected.items():
        assert core_module.classify_map_type(
            f"/t/Modelado2_Cabeza_{suffix}.png", map_types) == channel, suffix


def test_longest_suffix_wins(core_module):
    map_types = core_module.normalize_map_types([
        {"id": "baseColor", "suffixes": ["Base_Color"]},
        {"id": "emission", "suffixes": ["Color"]},
    ])
    assert core_module.classify_map_type("/t/Rock_Base_Color.png", map_types) == "baseColor"
    assert core_module.classify_map_type("/t/Rock_Color.png", map_types) == "emission"


def test_default_convention_still_uses_substrings(core_module):
    map_types = core_module.DEFAULT_CONFIG["map_types"]
    assert core_module.classify_map_type("/t/Rock_Roughness_2k.png", map_types) == "roughness"
    assert core_module.classify_map_type("/t/rock_mixed_ao.png", map_types) == "ao"


def test_scan_and_match_with_a_preset(core_module, tmp_path):
    for name in ("Rock_BC.png", "Rock_N.png", "Rock_R.png", "Car_Rim_BC.png"):
        (tmp_path / name).write_bytes(b"")
    config = _short(core_module)
    tex_map = core_module.scan_texture_folder(str(tmp_path), config["suffix_strip_list"])
    assert sorted(tex_map) == ["Car_Rim", "Rock"]

    match = core_module.match_objects_to_textures([("SM_Rock", None)], tex_map, config)[0]
    assert sorted(match["channels"]) == ["baseColor", "normal", "roughness"]


def test_list_naming_presets_puts_default_first_and_uses_labels(core_module):
    presets = core_module.list_naming_presets(core_module.DEFAULT_CONFIG, "es")
    assert presets[0] == ("default", "Por defecto (archivo de config)")
    assert [p for p, _label in presets] == ["default", "short_suffixes"]
    assert presets[1][1].startswith("Short suffixes")


def test_user_presets_are_read_from_the_config_file(core_module, app_dir):
    with open(os.path.join(app_dir, core_module.CONFIG_FILENAME), "w", encoding="utf-8") as f:
        json.dump({"naming_presets": {"studio": {"map_types": [
            {"id": "baseColor", "suffixes": ["Diffuse"]}]}}}, f)
    config = core_module.load_config(app_dir)
    assert [p for p, _label in core_module.list_naming_presets(config)] == ["default", "studio"]
    effective = core_module.apply_naming_preset(config, "studio")
    assert core_module.classify_map_type("/t/Rock_Diffuse.png", effective["map_types"]) == "baseColor"


def test_load_config_accepts_front_end_defaults(core_module, app_dir):
    defaults = dict(core_module.DEFAULT_CONFIG, render_engine="arnold")
    config = core_module.load_config(app_dir, defaults=defaults)
    assert config["render_engine"] == "arnold"
    # and a key the front-end added survives a round trip through the file
    assert core_module.load_config(app_dir, defaults=defaults)["render_engine"] == "arnold"
