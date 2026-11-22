"""
Tests for what process_textures builds: which input each channel ends up in,
and what happens with a map type the config declares but the tool can't wire.

These run on the maya.cmds stub, which records the nodes / connections /
attributes instead of touching a scene. The same network is also checked
against a real Maya (with Arnold) by run_in_mayapy.py — these are the fast
ones that run anywhere.
"""
import os


def _apply(ta, channels, **config_overrides):
    import maya.cmds as cmds
    files = {mid: f"/tex/Rock_{mid}.png" for mid in channels}
    config = dict(ta.core.DEFAULT_CONFIG, **config_overrides)
    ta.process_textures(None, "SM_Rock", mat_basename="Rock", config=config,
                        channel_files=files)
    return cmds


def _sources(cmds, destination):
    return [src for src, dst in cmds.connections if dst == destination]


def _node_type(cmds, plug):
    return cmds.created.get(plug.split(".")[0])


def test_every_standard_channel_reaches_its_arnold_input(ta):
    cmds = _apply(ta, ("baseColor", "roughness", "metallic", "normal", "emission", "opacity"))
    expected = {
        "specularRoughness": "file",
        "metalness": "file",
        "emissionColor": "file",
        "opacity": "file",
        "normalCamera": "bump2d",
    }
    for attr, node_type in expected.items():
        sources = _sources(cmds, f"M_Rock_MAT.{attr}")
        assert len(sources) == 1, attr
        assert _node_type(cmds, sources[0]) == node_type, attr
    assert cmds.created["M_Rock_MAT"] == "aiStandardSurface"


def test_scalar_inputs_read_the_luminance_not_a_missing_alpha_channel(ta):
    """A Substance export has no alpha channel, so outAlpha is a constant 1.0
    unless alphaIsLuminance is on. Without it, roughness/metallic/displacement
    come out flat."""
    cmds = _apply(ta, ("roughness", "metallic"))
    for attr in ("specularRoughness", "metalness"):
        plug = _sources(cmds, f"M_Rock_MAT.{attr}")[0]
        assert plug.endswith(".outAlpha"), attr
        assert cmds.set_attrs[plug.replace(".outAlpha", ".alphaIsLuminance")] is True, attr


def test_displacement_also_reads_the_luminance_when_opted_in(ta):
    cmds = _apply(ta, ("displacement",), enable_displacement_wiring=True)
    disp = _sources(cmds, "M_Rock_MATSG.displacementShader")
    assert len(disp) == 1 and _node_type(cmds, disp[0]) == "displacementShader"
    height = _sources(cmds, disp[0].split(".")[0] + ".displacement")[0]
    assert height.endswith(".outAlpha")
    assert cmds.set_attrs[height.replace(".outAlpha", ".alphaIsLuminance")] is True


def test_displacement_stays_opt_in(ta):
    cmds = _apply(ta, ("displacement",))
    assert not _sources(cmds, "M_Rock_MATSG.displacementShader")
    assert not any(cmds.created.get(n) == "displacementShader" for n in cmds.created)


def test_ao_is_multiplied_over_base_color(ta):
    cmds = _apply(ta, ("baseColor", "ao"))
    sources = _sources(cmds, "M_Rock_MAT.baseColor")
    assert [_node_type(cmds, s) for s in sources] == ["multiplyDivide"]


def test_a_map_type_the_tool_cannot_wire_creates_no_node_and_warns(ta):
    """The README invites extending map_types. An id with no wiring rule used
    to get a file + place2dTexture built and left dangling in the scene, with
    nothing said about it."""
    import maya.cmds as cmds
    config = dict(ta.core.DEFAULT_CONFIG)
    config["map_types"] = list(config["map_types"]) + [
        {"id": "specular", "match": ["_specular"], "color_space": "Raw", "raw": True}]

    ta.process_textures(None, "SM_Rock", mat_basename="Rock", config=config,
                        channel_files={"baseColor": "/tex/Rock_BaseColor.png",
                                       "specular": "/tex/Rock_Specular.png"})

    assert not any("Specular" in node for node in cmds.created), cmds.created
    assert any("specular" in w and "no wiring rule" in w for w in cmds.warnings), cmds.warnings
    # the channels it does know about are still applied
    assert _sources(cmds, "M_Rock_MAT.baseColor")


def test_udim_channels_switch_the_file_node_to_udim_tiling(ta):
    cmds = _apply(ta, ())
    import maya.cmds as cmds
    cmds.reset()
    ta.process_textures(None, "SM_Wall", mat_basename="Wall",
                        config=ta.core.DEFAULT_CONFIG,
                        channel_files={"baseColor": "/tex/Wall_BaseColor.<UDIM>.png"})
    tiling = [v for plug, v in cmds.set_attrs.items() if plug.endswith(".uvTilingMode")]
    assert tiling == [3]  # 3 = UDIM (Mari)


def test_the_window_fits_on_a_1080p_screen(ta):
    """The dialog used to demand a 1100 px minimum height and open at 1220, so
    on a 1080p screen the apply button sat below the bottom edge and the window
    could not be shrunk."""
    assert ta.TextureAutoloaderDialog.MINIMUM_HEIGHT <= 1032
    assert ta.TextureAutoloaderDialog.PREFERRED_HEIGHT >= ta.TextureAutoloaderDialog.MINIMUM_HEIGHT
