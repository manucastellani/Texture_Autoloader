"""
Tests for the Unreal port's pure helpers: which names a Material Slot is
matched with, asset naming, import settings per channel, and config
merging. Plus slot-level matching end to end through the shared core.
"""
import json
import os


def test_uses_the_shared_core_from_dcc_mejoras(tal):
    assert tal.core.__file__.replace("\\", "/").endswith("dcc_mejoras/core/texture_autoloader_core.py")


def test_slot_candidates_try_mesh_plus_slot_then_slot_then_mesh(tal):
    config = tal.UNREAL_DEFAULT_CONFIG
    assert tal.slot_candidates("SM_Hero", "Body", "material_id", config) == [
        "Hero_Body", "Body", "Hero"]
    assert tal.slot_candidates("SK_Hero", "M_Head_MAT", "material_id", config) == [
        "Hero_Head", "Head", "Hero"]


def test_generic_slot_names_fall_back_to_the_mesh(tal):
    config = tal.UNREAL_DEFAULT_CONFIG
    for slot in ("WorldGridMaterial", "None", "", "lambert1", "DefaultMaterial"):
        assert tal.slot_candidates("SM_Crate", slot, "material_id", config) == ["Crate"], slot


def test_object_name_mode_ignores_slot_names(tal):
    assert tal.slot_candidates("SM_Hero_LOD0", "Body", "object_name",
                               tal.UNREAL_DEFAULT_CONFIG) == ["Hero"]


def test_asset_name_sanitizes_and_prefixes(tal):
    assert tal.asset_name("Hero_Body_BaseColor", "T_") == "T_Hero_Body_BaseColor"
    assert tal.asset_name("T_Rock_N", "T_") == "T_Rock_N"
    assert tal.asset_name("Wall BaseColor.1001", "T_") == "T_Wall_BaseColor_1001"
    assert tal.asset_name("Hero_Body", "MI_") == "MI_Hero_Body"


def test_texture_settings_per_channel(tal):
    config = tal.UNREAL_DEFAULT_CONFIG
    assert tal.texture_settings_for("baseColor", config) == (True, "TC_DEFAULT")
    assert tal.texture_settings_for("emission", config) == (True, "TC_DEFAULT")
    assert tal.texture_settings_for("normal", config) == (False, "TC_NORMALMAP")
    for channel in ("roughness", "metallic", "ao", "opacity"):
        assert tal.texture_settings_for(channel, config) == (False, "TC_MASKS"), channel


def test_texture_settings_can_be_overridden_per_channel(tal):
    config = tal.merge_unreal_section(dict(tal.UNREAL_DEFAULT_CONFIG, unreal={
        "texture_settings": {"roughness": {"compression": "TC_GRAYSCALE"}}}))
    assert tal.texture_settings_for("roughness", config) == (False, "TC_GRAYSCALE")


def test_partial_unreal_section_keeps_the_other_defaults(tal):
    config = tal.merge_unreal_section(dict(tal.UNREAL_DEFAULT_CONFIG, unreal={
        "master_material": "/Game/Studio/M_Master", "parameters": {"baseColor": "Albedo"}}))
    section = config["unreal"]
    assert section["master_material"] == "/Game/Studio/M_Master"
    assert section["texture_prefix"] == "T_"
    assert section["parameters"]["baseColor"] == "Albedo"
    assert section["parameters"]["normal"] == "Normal"


def test_load_config_writes_and_reads_the_unreal_section(tal):
    config = tal.load_config()
    assert config["match_mode"] == "material_id"
    assert config["unreal"]["material_instance_prefix"] == "MI_"
    path = os.path.join(tal._app_dir(), tal.core.CONFIG_FILENAME)
    with open(path, encoding="utf-8") as f:
        assert "unreal" in json.load(f)


def test_slots_match_their_own_texture_sets(tal):
    """What match_meshes feeds the core, without Unreal: one entry per slot."""
    config = tal.UNREAL_DEFAULT_CONFIG
    tex_map = {"Hero_Body": ["/t/Hero_Body_BaseColor.png"],
               "Hero_Head": ["/t/Hero_Head_BaseColor.png"],
               "Villain_Body": ["/t/Villain_Body_BaseColor.png"]}
    named = [(tal.slot_key("SM_Hero", slot), tal.slot_candidates("SM_Hero", slot, "material_id", config))
             for slot in ("Body", "Head")]
    matches = tal.core.match_names_to_textures(named, tex_map, config)
    assert [(m["obj"], m["tex_base"]) for m in matches] == [
        ("SM_Hero · Body", "Hero_Body"), ("SM_Hero · Head", "Hero_Head")]


def test_write_png_produces_a_valid_png(tal, tmp_path):
    path = tmp_path / "flat.png"
    tal.write_png(str(path), (128, 128, 255))
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB`\x82")
