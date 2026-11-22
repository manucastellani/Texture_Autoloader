"""
Tests for the render engine templates (ENGINE_TEMPLATES): which shader
each engine creates and which input every channel ends up in. Runs on the
maya.cmds stub, which records nodes / connections / attributes — so the
Redshift and V-Ray templates get checked without either renderer
installed (what the stub can't check is that the renderer really has
those attributes; that's what the attributeQuery guard + report are for).
"""
import pytest

CHANNELS = ("baseColor", "roughness", "metallic", "normal", "emission", "opacity", "ao")


def _apply(ta, engine, channels=CHANNELS, **config_overrides):
    import maya.cmds as cmds
    files = {mid: f"/tex/Rock_{mid}.png" for mid in channels}
    config = dict(ta.MAYA_DEFAULT_CONFIG, **config_overrides)
    result = ta.process_textures(None, "SM_Rock", mat_basename="Rock", config=config,
                                 channel_files=files, engine=engine)
    return cmds, result


def _sources(cmds, destination):
    return [src for src, dst in cmds._connections if dst == destination]


def _node_type_of(cmds, plug):
    return cmds._created.get(plug.split(".")[0])


EXPECTED = {
    # engine: (shader type, {channel: input on the shader}, normal helper node)
    "arnold": ("aiStandardSurface", {
        "roughness": "specularRoughness", "metallic": "metalness",
        "emission": "emissionColor", "opacity": "opacity"}, "bump2d"),
    "redshift": ("RedshiftStandardMaterial", {
        "roughness": "refl_roughness", "metallic": "metalness",
        "emission": "emission_color", "opacity": "opacity_color"}, "RedshiftBumpMap"),
    "vray": ("VRayMtl", {
        "roughness": "reflectionGlossiness", "metallic": "metalness",
        "emission": "illumColor", "opacity": "opacityMap"}, None),
}


@pytest.mark.parametrize("engine", sorted(EXPECTED))
def test_engine_template_wires_every_channel(ta, engine):
    shader_type, inputs, normal_node = EXPECTED[engine]
    cmds, result = _apply(ta, engine)

    assert result["material"] == "M_Rock_MAT"
    assert cmds._created["M_Rock_MAT"] == shader_type
    assert sorted(result["wired"]) == sorted(CHANNELS)
    assert not result["skipped"] and not result["failed"]

    for channel, attr in inputs.items():
        sources = _sources(cmds, f"M_Rock_MAT.{attr}")
        assert len(sources) == 1 and _node_type_of(cmds, sources[0]) == "file", channel

    # scalar inputs read the luminance, not a (missing) alpha channel
    rough_src = _sources(cmds, f"M_Rock_MAT.{inputs['roughness']}")[0]
    assert rough_src.endswith(".outAlpha")
    assert cmds._set_attrs[rough_src.replace(".outAlpha", ".alphaIsLuminance")] is True

    # AO is multiplied over base color, on whatever the base color input is called
    base_attr = ta.ENGINE_TEMPLATES[engine]["channels"]["baseColor"]["attr"]
    base_src = _sources(cmds, f"M_Rock_MAT.{base_attr}")
    assert [_node_type_of(cmds, s) for s in base_src] == ["multiplyDivide"]

    normal_attr = ta.ENGINE_TEMPLATES[engine]["channels"]["normal"]["attr"]
    normal_src = _sources(cmds, f"M_Rock_MAT.{normal_attr}")
    assert len(normal_src) == 1
    assert _node_type_of(cmds, normal_src[0]) == (normal_node or "file")


def test_arnold_normal_map_is_a_tangent_space_bump2d(ta):
    cmds, _result = _apply(ta, "arnold", channels=("normal",))
    bump = _sources(cmds, "M_Rock_MAT.normalCamera")[0].split(".")[0]
    assert cmds._set_attrs[f"{bump}.bumpInterp"] == 1
    assert _sources(cmds, f"{bump}.bumpValue")[0].endswith(".outAlpha")


def test_redshift_normal_map_goes_through_a_tangent_space_bump_map(ta):
    cmds, _result = _apply(ta, "redshift", channels=("normal", "emission"))
    bump = _sources(cmds, "M_Rock_MAT.bump_input")[0].split(".")[0]
    assert cmds._set_attrs[f"{bump}.inputType"] == 1
    assert _sources(cmds, f"{bump}.input")[0].endswith(".outColor")
    assert cmds._set_attrs["M_Rock_MAT.emission_weight"] == 1.0


def test_vray_uses_the_metalness_workflow(ta):
    cmds, _result = _apply(ta, "vray", channels=("normal",))
    assert cmds._set_attrs["M_Rock_MAT.reflectionColor"] == (1.0, 1.0, 1.0)
    assert cmds._set_attrs["M_Rock_MAT.useRoughness"] == 1
    assert cmds._set_attrs["M_Rock_MAT.brdfType"] == 3
    assert cmds._set_attrs["M_Rock_MAT.bumpMapType"] == 1
    assert _sources(cmds, "M_Rock_MAT.bumpMap")[0].endswith(".outColor")


@pytest.mark.parametrize("engine", sorted(EXPECTED))
def test_displacement_reads_luminance_and_goes_to_the_shading_group(ta, engine):
    cmds, result = _apply(ta, engine, channels=("displacement",),
                          enable_displacement_wiring=True)
    assert "displacement" in result["wired"]
    helper = _sources(cmds, "M_Rock_MATSG.displacementShader")[0].split(".")[0]
    file_plug = [s for s in (_sources(cmds, f"{helper}.displacement")
                             + _sources(cmds, f"{helper}.texMap"))][0]
    if file_plug.endswith(".outAlpha"):
        assert cmds._set_attrs[file_plug.replace(".outAlpha", ".alphaIsLuminance")] is True


def test_a_missing_attribute_is_reported_instead_of_breaking_the_object(ta):
    import maya.cmds as cmds
    cmds._missing_attrs.add(("VRayMtl", "illumColor"))
    _cmds, result = _apply(ta, "vray", channels=("baseColor", "emission"))
    assert result["skipped"]["emission"] == {
        "reason": "missing_attr", "target": "VRayMtl", "attr": "illumColor"}
    assert "baseColor" in result["wired"]


def test_engine_without_its_plugin_loaded_raises_a_clear_error(ta):
    import maya.cmds as cmds
    cmds._loaded_plugins = {"mtoa"}
    with pytest.raises(RuntimeError, match="redshift4maya"):
        _apply(ta, "redshift", channels=("baseColor",))


def test_unknown_engine_raises(ta):
    with pytest.raises(ValueError, match="unknown render engine"):
        _apply(ta, "cycles", channels=("baseColor",))


def test_engine_defaults_to_the_config(ta):
    import maya.cmds as cmds
    config = dict(ta.MAYA_DEFAULT_CONFIG, render_engine="vray")
    ta.process_textures(None, "SM_Rock", mat_basename="Rock", config=config,
                        channel_files={"baseColor": "/tex/Rock_BaseColor.png"})
    assert cmds._created["M_Rock_MAT"] == "VRayMtl"


def test_every_template_only_uses_known_channels(ta):
    known = {mt["id"] for mt in ta.core.DEFAULT_CONFIG["map_types"]}
    for engine, template in ta.ENGINE_TEMPLATES.items():
        assert set(template["channels"]) <= known, engine
