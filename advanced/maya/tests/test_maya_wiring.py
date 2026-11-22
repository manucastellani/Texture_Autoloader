"""
Tests for the parts of process_textures that are the same whatever render
engine is selected — the per-engine templates themselves are covered by
test_maya_engines.py, and the real network inside Maya by
../../../tests/integration_maya.py.

These run on the maya.cmds stub, which records the nodes / connections /
attributes instead of touching a scene.
"""


def _apply(ta, channels, **config_overrides):
    import maya.cmds as cmds
    files = {mid: f"/tex/Rock_{mid}.png" for mid in channels}
    config = dict(ta.MAYA_DEFAULT_CONFIG, **config_overrides)
    result = ta.process_textures(None, "SM_Rock", mat_basename="Rock", config=config,
                                 channel_files=files)
    return cmds, result


def _sources(cmds, destination):
    return [src for src, dst in cmds._connections if dst == destination]


def test_displacement_stays_opt_in(ta):
    cmds, result = _apply(ta, ("baseColor", "displacement"))
    assert not _sources(cmds, "M_Rock_MATSG.displacementShader")
    assert "displacementShader" not in cmds._created.values()
    assert result["skipped"]["displacement"] == {"reason": "displacement_off"}
    assert "baseColor" in result["wired"]


def test_a_udim_channel_switches_the_file_node_to_udim_tiling(ta):
    cmds, _result = _apply(ta, ())
    import maya.cmds as cmds
    cmds.reset()
    ta.process_textures(None, "SM_Wall", mat_basename="Wall",
                        config=ta.MAYA_DEFAULT_CONFIG,
                        channel_files={"baseColor": "/tex/Wall_BaseColor.<UDIM>.png"})
    tiling = [value for plug, value in cmds._set_attrs.items()
              if plug.endswith(".uvTilingMode")]
    assert tiling == [3]  # 3 = UDIM (Mari)


def test_a_map_type_the_engine_cannot_wire_creates_no_node_and_is_reported(ta):
    """The README invites extending map_types. An id no engine template knows
    used to get a file + place2dTexture built and left dangling in the scene,
    with nothing said about it."""
    import maya.cmds as cmds
    config = dict(ta.MAYA_DEFAULT_CONFIG)
    config["map_types"] = list(config["map_types"]) + [
        {"id": "specular", "match": ["_specular"], "color_space": "Raw", "raw": True}]

    result = ta.process_textures(None, "SM_Rock", mat_basename="Rock", config=config,
                                 channel_files={"baseColor": "/tex/Rock_BaseColor.png",
                                                "specular": "/tex/Rock_Specular.png"})

    assert not any("Specular" in node for node in cmds._created), cmds._created
    assert result["skipped"]["specular"]["reason"] == "no_target"
    assert "baseColor" in result["wired"]  # the known channels still apply


def test_the_report_lists_the_unwired_map_type(ta):
    config = dict(ta.MAYA_DEFAULT_CONFIG)
    config["map_types"] = list(config["map_types"]) + [
        {"id": "specular", "match": ["_specular"], "color_space": "Raw", "raw": True}]
    tex_map = {"Rock": ["/tex/Rock_BaseColor.png", "/tex/Rock_Specular.png"]}
    matches = [ta.core.build_match_entry("SM_Rock", "Rock", 0.9, tex_map, config)]
    ta.apply_auto_textures(matches, config)

    report = ta.core.build_report(matches, "en")
    assert "✔ Rock_BaseColor.png → baseColor" in report
    assert "Rock_Specular.png → specular" in report
    assert "aiStandardSurface has no input for this channel" in report


def test_the_window_fits_on_a_1080p_screen(ta):
    """The dialog used to demand a 1100 px minimum height and open at 1220, so
    on a 1080p screen the apply button sat below the bottom edge and the window
    could not be shrunk."""
    dialog = ta.TextureAutoloaderDialog
    assert dialog.MINIMUM_HEIGHT <= 1032
    assert dialog.PREFERRED_HEIGHT >= dialog.MINIMUM_HEIGHT
