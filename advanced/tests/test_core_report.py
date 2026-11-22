"""
Tests for the post-run ✔/✘ report: what the core keeps track of while
matching/applying (unrecognized files, ignored duplicates, per-object
status) and the plain-text report built from it.
"""


def _touch(folder, *names):
    for name in names:
        (folder / name).write_bytes(b"")


def test_scan_attaches_unknown_map_suffix_to_its_texture_set(core_module, tmp_path):
    _touch(tmp_path, "Rock_BaseColor.png", "Rock_Curvature.png", "Rock_Large_BaseColor.png",
           "Rock_Large_Curvature.png")
    tex_map = core_module.scan_texture_folder(
        str(tmp_path), core_module.DEFAULT_CONFIG["suffix_strip_list"])

    assert sorted(tex_map) == ["Rock", "Rock_Large"]
    assert sorted(p.split("\\")[-1].split("/")[-1] for p in tex_map["Rock"]) == [
        "Rock_BaseColor.png", "Rock_Curvature.png"]
    # the longest set name wins
    assert any(p.endswith("Rock_Large_Curvature.png") for p in tex_map["Rock_Large"])


def test_scan_keeps_unknown_map_suffix_as_its_own_set_when_nothing_owns_it(core_module, tmp_path):
    _touch(tmp_path, "Lonely_Curvature.png")
    tex_map = core_module.scan_texture_folder(
        str(tmp_path), core_module.DEFAULT_CONFIG["suffix_strip_list"])
    assert list(tex_map) == ["Lonely_Curvature"]


def test_build_match_entry_tracks_unrecognized_files_and_ignored_duplicates(core_module):
    tex_map = {"Rock": ["/t/Rock_BaseColor_1024.png", "/t/Rock_BaseColor_2048.png",
                        "/t/Rock_Curvature.png"]}
    entry = core_module.build_match_entry("SM_Rock", "Rock", 0.9, tex_map,
                                          core_module.DEFAULT_CONFIG)
    assert entry["unrecognized"] == ["/t/Rock_Curvature.png"]
    channel = entry["channels"]["baseColor"]
    assert channel["file"] == "/t/Rock_BaseColor_1024.png"
    assert channel["ignored"] == ["/t/Rock_BaseColor_2048.png"]


def test_udim_tiles_are_not_reported_as_ignored_duplicates(core_module):
    tex_map = {"Wall": ["/t/Wall_BaseColor.1001.png", "/t/Wall_BaseColor.1002.png"]}
    entry = core_module.build_match_entry("SM_Wall", "Wall", 0.9, tex_map,
                                          core_module.DEFAULT_CONFIG)
    assert entry["channels"]["baseColor"]["is_udim"] is True
    assert entry["channels"]["baseColor"]["ignored"] == []


def test_build_entry_from_files_matches_manual_mode(core_module):
    entry = core_module.build_entry_from_files(
        "pCube1", "pCube1", ["/t/Box_BaseColor.png", "/t/Box_Notes.txt.png"],
        core_module.DEFAULT_CONFIG)
    assert list(entry["channels"]) == ["baseColor"]
    assert entry["unrecognized"] == ["/t/Box_Notes.txt.png"]


def _matches(core_module):
    tex_map = {
        "Rock": ["/t/Rock_BaseColor.png", "/t/Rock_Height.png", "/t/Rock_Emissive.png",
                 "/t/Rock_Roughness.png", "/t/Rock_Curvature.png"],
        "Crate": ["/t/Crate_BaseColor.png"],
    }
    matches = [
        core_module.build_match_entry("|grp|SM_Rock", "Rock", 0.95, tex_map,
                                      core_module.DEFAULT_CONFIG),
        core_module.build_match_entry("SM_Tree", None, 0.2, tex_map, core_module.DEFAULT_CONFIG),
    ]
    matches[0]["channels"]["roughness"]["enabled"] = False
    return tex_map, matches


def _fake_apply(core_module):
    def apply_one(obj, mat_basename, channel_files):
        result = core_module.new_apply_result(material=f"M_{mat_basename}_MAT")
        result["wired"]["baseColor"] = channel_files["baseColor"]
        result["skipped"]["displacement"] = {"reason": "displacement_off"}
        result["failed"]["emission"] = "boom"
        return result
    return apply_one


def test_apply_auto_textures_records_status_and_result(core_module):
    _tex_map, matches = _matches(core_module)
    applied, skipped = core_module.apply_auto_textures(
        matches, core_module.DEFAULT_CONFIG, apply_one_fn=_fake_apply(core_module))
    assert (applied, skipped) == (1, 1)
    assert matches[0]["status"] == "applied"
    assert matches[0]["result"]["material"] == "M_Rock_MAT"
    assert matches[1]["status"] == "no_match"


def test_apply_auto_textures_isolates_an_error_to_its_object(core_module):
    tex_map = {"A": ["/t/A_BaseColor.png"], "B": ["/t/B_BaseColor.png"]}
    matches = [core_module.build_match_entry(o, s, 0.9, tex_map, core_module.DEFAULT_CONFIG)
               for o, s in (("SM_A", "A"), ("SM_B", "B"))]

    def apply_one(obj, _mat_basename, _channel_files):
        if obj == "SM_A":
            raise RuntimeError("node creation failed")

    applied, skipped = core_module.apply_auto_textures(
        matches, core_module.DEFAULT_CONFIG, apply_one_fn=apply_one)
    assert (applied, skipped) == (1, 1)
    assert matches[0]["status"] == "error"
    assert "node creation failed" in matches[0]["error"]
    assert matches[1]["status"] == "applied"


def test_apply_auto_textures_marks_the_rest_as_cancelled(core_module):
    tex_map = {"A": ["/t/A_BaseColor.png"], "B": ["/t/B_BaseColor.png"]}
    matches = [core_module.build_match_entry(o, s, 0.9, tex_map, core_module.DEFAULT_CONFIG)
               for o, s in (("SM_A", "A"), ("SM_B", "B"))]
    core_module.apply_auto_textures(
        matches, core_module.DEFAULT_CONFIG, apply_one_fn=lambda *a: None,
        progress_cb=lambda i, total, obj: i >= 1)
    assert [m["status"] for m in matches] == ["applied", "cancelled"]


def test_build_report_lists_every_file_with_its_outcome(core_module):
    tex_map, matches = _matches(core_module)
    core_module.apply_auto_textures(
        matches, core_module.DEFAULT_CONFIG, apply_one_fn=_fake_apply(core_module))
    report = core_module.build_report(matches, "en", tex_map=tex_map)

    assert "SM_Rock  →  Rock  (95%)  ·  M_Rock_MAT" in report
    assert "✔ Rock_BaseColor.png → baseColor" in report
    assert "– Rock_Height.png → displacement: not wired, displacement is opt-in" in report
    assert "✘ Rock_Emissive.png → emission: error: boom" in report
    assert "– Rock_Roughness.png → roughness: disabled in the preview" in report
    assert "✘ no match: Rock_Curvature.png" in report
    assert "SM_Tree  →  ✘ no texture set matched" in report
    assert "Texture sets with no object: Crate (1)" in report
    assert report.splitlines()[-1] == "1/2 object(s) applied  ·  1 ✔  ·  3 ✘  ·  2 –"


def test_build_report_in_spanish(core_module):
    tex_map, matches = _matches(core_module)
    core_module.apply_auto_textures(
        matches, core_module.DEFAULT_CONFIG, apply_one_fn=_fake_apply(core_module))
    report = core_module.build_report(matches, "es")
    assert "✘ sin match: Rock_Curvature.png" in report
    assert "SM_Tree  →  ✘ ningún set de texturas coincide" in report


def test_build_report_preview_lists_planned_channels(core_module):
    tex_map, matches = _matches(core_module)
    report = core_module.build_report(matches, "en", preview=True)
    assert report.splitlines()[0] == "TEXTURE AUTOLOADER — PREVIEW"
    assert "• Rock_BaseColor.png → baseColor" in report
    assert "✘ no match: Rock_Curvature.png" in report
    assert report.splitlines()[-1] == "1 / 2 objects matched"


def test_build_report_when_the_front_end_returns_no_per_channel_result(core_module):
    tex_map = {"A": ["/t/A_BaseColor.png"]}
    matches = [core_module.build_match_entry("SM_A", "A", 0.9, tex_map,
                                             core_module.DEFAULT_CONFIG)]
    core_module.apply_auto_textures(matches, core_module.DEFAULT_CONFIG,
                                    apply_one_fn=lambda *a: None)
    assert "✔ A_BaseColor.png → baseColor" in core_module.build_report(matches, "en")


def test_build_report_marks_udim_channels(core_module):
    tex_map = {"Wall": ["/t/Wall_BaseColor.1001.png", "/t/Wall_BaseColor.1002.png"]}
    matches = [core_module.build_match_entry("SM_Wall", "Wall", 0.9, tex_map,
                                             core_module.DEFAULT_CONFIG)]
    report = core_module.build_report(matches, "en", preview=True)
    assert "• Wall_BaseColor.<UDIM>.png → baseColor" in report
