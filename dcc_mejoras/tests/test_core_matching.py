"""
Tests for core.match_objects_to_textures — the DCC-agnostic matching
entry point that both the Maya and Blender front-ends call. It takes
pre-resolved (object_name, assigned_material_or_None) tuples instead of
touching any scene itself, which is what makes it directly testable with
no stubs.
"""


def test_match_objects_to_textures_object_name_mode(core_module):
    entries = [("SM_Rock", None)]
    tex_map = {"Rock": ["/tex/Rock_BaseColor.png"]}
    matches = core_module.match_objects_to_textures(
        entries, tex_map, core_module.DEFAULT_CONFIG, match_mode="object_name")
    assert matches[0]["tex_base"] == "Rock"


def test_match_objects_to_textures_material_id_mode(core_module):
    entries = [("SM_Character", "Skin_MAT")]
    tex_map = {"Skin": ["/tex/Skin_BaseColor.png"]}
    matches = core_module.match_objects_to_textures(
        entries, tex_map, core_module.DEFAULT_CONFIG, match_mode="material_id")
    assert matches[0]["tex_base"] == "Skin"


def test_match_objects_to_textures_material_id_falls_back_to_object_name(core_module):
    """If the entry has no assigned material (None), material_id mode
    never leaves it unmatched — it falls back to the object's own name
    for that entry."""
    entries = [("SM_NoMat", None)]
    tex_map = {"NoMat": ["/tex/NoMat_BaseColor.png"]}
    matches = core_module.match_objects_to_textures(
        entries, tex_map, core_module.DEFAULT_CONFIG, match_mode="material_id")
    assert matches[0]["tex_base"] == "NoMat"


def test_build_match_entry_populates_channels_from_matched_set(core_module):
    tex_map = {"Rock": ["/tex/Rock_BaseColor.png", "/tex/Rock_Roughness.png"]}
    entry = core_module.build_match_entry(
        "SM_Rock", "Rock", 0.95, tex_map, core_module.DEFAULT_CONFIG)
    assert entry["channels"]["baseColor"]["enabled"] is True
    assert entry["channels"]["roughness"]["file"] == "/tex/Rock_Roughness.png"


def test_build_match_entry_no_channels_when_unmatched(core_module):
    entry = core_module.build_match_entry("SM_Rock", None, 0.0, {}, core_module.DEFAULT_CONFIG)
    assert entry["channels"] == {}


def test_apply_auto_textures_applies_only_enabled_channels(core_module):
    applied_calls = []

    def fake_apply(obj, mat_basename, channel_files):
        applied_calls.append((obj, mat_basename, channel_files))

    matches = [
        core_module.build_match_entry(
            "SM_Rock", "Rock",
            0.9, {"Rock": ["/tex/Rock_BaseColor.png", "/tex/Rock_Roughness.png"]},
            core_module.DEFAULT_CONFIG),
    ]
    matches[0]["channels"]["roughness"]["enabled"] = False

    applied, skipped = core_module.apply_auto_textures(
        matches, core_module.DEFAULT_CONFIG, apply_one_fn=fake_apply)

    assert applied == 1
    assert skipped == 0
    assert "roughness" not in applied_calls[0][2]
    assert "baseColor" in applied_calls[0][2]


def test_apply_auto_textures_skips_unmatched_objects(core_module):
    calls = []
    matches = [core_module.build_match_entry("SM_Rock", None, 0.0, {}, core_module.DEFAULT_CONFIG)]

    applied, skipped = core_module.apply_auto_textures(
        matches, core_module.DEFAULT_CONFIG, apply_one_fn=lambda *a: calls.append(a))

    assert applied == 0
    assert skipped == 1
    assert calls == []


def test_apply_auto_textures_progress_callback_can_cancel(core_module):
    tex_map = {"A": ["/tex/A_BaseColor.png"], "B": ["/tex/B_BaseColor.png"]}
    matches = [
        core_module.build_match_entry("SM_A", "A", 0.9, tex_map, core_module.DEFAULT_CONFIG),
        core_module.build_match_entry("SM_B", "B", 0.9, tex_map, core_module.DEFAULT_CONFIG),
    ]
    calls = []

    def cancel_after_first(i, total, obj):
        return i >= 1  # cancela antes de procesar el segundo objeto

    applied, skipped = core_module.apply_auto_textures(
        matches, core_module.DEFAULT_CONFIG,
        apply_one_fn=lambda *a: calls.append(a),
        progress_cb=cancel_after_first)

    assert applied == 1
    assert len(calls) == 1
