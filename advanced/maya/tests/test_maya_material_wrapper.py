"""
Tests for the Maya-specific parts of texture_autoloader_maya.py: the
functions that actually call maya.cmds to look at the scene, before
delegating the real matching decision to the shared core. The core's own
matching logic (thresholds, UDIM, Material ID fallback) is already
covered without any stub in ../../tests/ — these tests only check that
the Maya wrapper correctly resolves what to hand the core.
"""


def test_get_assigned_material_name_returns_real_shader(ta):
    import maya.cmds as cmds
    cmds._shape_connections["SM_Character"] = {"shapes": ["SM_CharacterShape"], "type": "mesh"}
    cmds._shape_connections["SM_CharacterShape"] = {
        "shapes": ["SM_CharacterShape"], "type": "mesh", "shadingEngines": ["charSG"]}
    cmds._sg_surface_shader["charSG"] = "Skin_MAT"

    assert ta._get_assigned_material_name("SM_Character") == "Skin_MAT"


def test_get_assigned_material_name_ignores_default_shading_group(ta):
    import maya.cmds as cmds
    cmds._shape_connections["SM_NoMat"] = {"shapes": ["SM_NoMatShape"], "type": "mesh"}
    cmds._shape_connections["SM_NoMatShape"] = {
        "shapes": ["SM_NoMatShape"], "type": "mesh", "shadingEngines": ["initialShadingGroup"]}

    assert ta._get_assigned_material_name("SM_NoMat") is None


def test_get_assigned_material_name_ignores_default_shader_on_custom_sg(ta):
    import maya.cmds as cmds
    cmds._shape_connections["SM_Odd"] = {"shapes": ["SM_OddShape"], "type": "mesh"}
    cmds._shape_connections["SM_OddShape"] = {
        "shapes": ["SM_OddShape"], "type": "mesh", "shadingEngines": ["customSG"]}
    cmds._sg_surface_shader["customSG"] = "lambert1"

    assert ta._get_assigned_material_name("SM_Odd") is None


def test_match_objects_to_textures_wrapper_object_name_mode(ta):
    import maya.cmds as cmds
    cmds._shape_connections["SM_Rock"] = {"shapes": ["SM_RockShape"], "type": "mesh"}
    cmds._shape_connections["SM_RockShape"] = {"shapes": ["SM_RockShape"], "type": "mesh"}

    tex_map = {"Rock": ["/tex/Rock_BaseColor.png"]}
    matches = ta.match_objects_to_textures(
        ["SM_Rock"], tex_map, ta.core.DEFAULT_CONFIG, match_mode="object_name")

    assert matches[0]["tex_base"] == "Rock"


def test_match_objects_to_textures_wrapper_material_id_mode(ta):
    import maya.cmds as cmds
    cmds._shape_connections["SM_Character"] = {"shapes": ["SM_CharacterShape"], "type": "mesh"}
    cmds._shape_connections["SM_CharacterShape"] = {
        "shapes": ["SM_CharacterShape"], "type": "mesh", "shadingEngines": ["charSG"]}
    cmds._sg_surface_shader["charSG"] = "Skin_MAT"

    tex_map = {"Skin": ["/tex/Skin_BaseColor.png"]}
    matches = ta.match_objects_to_textures(
        ["SM_Character"], tex_map, ta.core.DEFAULT_CONFIG, match_mode="material_id")

    assert matches[0]["tex_base"] == "Skin"


def test_match_objects_to_textures_wrapper_skips_non_mesh_objects(ta):
    import maya.cmds as cmds
    cmds._shape_connections["group1"] = {"shapes": [], "type": "transform"}

    matches = ta.match_objects_to_textures(["group1"], {}, ta.core.DEFAULT_CONFIG)
    assert matches == []


def test_has_autoloader_material_recognizes_own_naming_pattern(ta):
    import maya.cmds as cmds
    cmds._shape_connections["SM_Character"] = {"shapes": ["SM_CharacterShape"], "type": "mesh"}
    cmds._shape_connections["SM_CharacterShape"] = {
        "shapes": ["SM_CharacterShape"], "type": "mesh", "shadingEngines": ["charSG"]}
    cmds._sg_surface_shader["charSG"] = "M_Character_MAT"

    assert ta.has_autoloader_material("SM_Character") is True


def test_has_autoloader_material_false_for_foreign_material(ta):
    import maya.cmds as cmds
    cmds._shape_connections["SM_Character"] = {"shapes": ["SM_CharacterShape"], "type": "mesh"}
    cmds._shape_connections["SM_CharacterShape"] = {
        "shapes": ["SM_CharacterShape"], "type": "mesh", "shadingEngines": ["charSG"]}
    cmds._sg_surface_shader["charSG"] = "SomeOtherArtists_Material"

    assert ta.has_autoloader_material("SM_Character") is False


def test_config_and_state_are_isolated_from_the_real_repo(ta, tmp_path):
    """El módulo bajo test debe resolver su config/estado dentro de la
    copia temporal (junto a su propio __file__), nunca en el repo real."""
    config = ta.core.load_config(ta._app_dir(), warn_fn=ta._warn)
    assert config["match_threshold"] == ta.core.DEFAULT_CONFIG["match_threshold"]
    assert str(tmp_path) in ta._app_dir()
