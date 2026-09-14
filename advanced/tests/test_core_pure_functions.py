"""Tests for the pure string/matching/UDIM logic in texture_autoloader_core."""


def test_tex_base_name_strips_suffix_and_extension(core_module):
    result = core_module.tex_base_name(
        "Wall_BaseColor.png", core_module.DEFAULT_CONFIG["suffix_strip_list"])
    assert result == "Wall"


def test_tex_base_name_strips_resolution_modifier(core_module):
    result = core_module.tex_base_name(
        "Wall_BaseColor_2K.png", core_module.DEFAULT_CONFIG["suffix_strip_list"])
    assert result == "Wall"


def test_mesh_base_name_strips_prefix_lod_and_trailing_index(core_module):
    assert core_module.mesh_base_name("SM_Character_LOD0", ["SM_"]) == "Character"
    assert core_module.mesh_base_name("SM_Rock_003", ["SM_"]) == "Rock"
    assert core_module.mesh_base_name("SM_PropShape", ["SM_"]) == "Prop"


def test_material_base_name_strips_prefix_and_shader_suffix(core_module):
    assert core_module.material_base_name("M_Skin_MAT", ["M_", "SM_"]) == "Skin"
    assert core_module.material_base_name("Metal_Shader", []) == "Metal"
    assert core_module.material_base_name("Cloth_SG", []) == "Cloth"


def test_collapse_udim_set_detects_real_udim_tiles(core_module):
    files = [f"/tex/Wall_BaseColor.100{i}.png" for i in (1, 2, 3)]
    representative, is_udim = core_module.collapse_udim_set(files)
    assert is_udim is True
    assert "<UDIM>" in representative


def test_collapse_udim_set_does_not_confuse_resolution_suffix_with_udim(core_module):
    """Hotfix inherited from v2.2: two exports of the same map at different
    resolutions ("_1024" / "_2048") are not UDIM tiles, even though the
    number falls inside the 1001-1999 range used to detect real tiles."""
    files = ["/tex/Wall_BaseColor_1024.png", "/tex/Wall_BaseColor_2048.png"]
    representative, is_udim = core_module.collapse_udim_set(files)
    assert is_udim is False
    assert representative == files[0]


def test_collapse_udim_set_single_file_is_never_udim(core_module):
    representative, is_udim = core_module.collapse_udim_set(["/tex/Wall_BaseColor.png"])
    assert is_udim is False


def test_collapse_udim_set_calls_warn_fn_when_not_real_udim(core_module):
    warnings = []
    files = ["/tex/Wall_BaseColor_1024.png", "/tex/Wall_BaseColor_2048.png"]
    core_module.collapse_udim_set(files, warn_fn=warnings.append)
    assert len(warnings) == 1
    assert "UDIM" in warnings[0]


def test_get_udim_tile_files_extracts_tile_numbers(core_module):
    representative = "/tex/Wall_BaseColor.<UDIM>.png"
    all_files = [
        "/tex/Wall_BaseColor.1001.png",
        "/tex/Wall_BaseColor.1002.png",
        "/tex/Wall_Roughness.1001.png",  # distinto tipo de mapa, no debe aparecer
    ]
    tiles = core_module.get_udim_tile_files(representative, all_files)
    assert tiles == {
        1001: "/tex/Wall_BaseColor.1001.png",
        1002: "/tex/Wall_BaseColor.1002.png",
    }


def test_bucket_files_by_type_first_match_wins_and_tracks_unmatched(core_module):
    files = ["/t/Wall_BaseColor.png", "/t/Wall_Roughness.png", "/t/Wall_Unknown.tiff"]
    buckets, unmatched = core_module.bucket_files_by_type(
        files, core_module.DEFAULT_CONFIG["map_types"])
    assert buckets["baseColor"] == ["/t/Wall_BaseColor.png"]
    assert buckets["roughness"] == ["/t/Wall_Roughness.png"]
    assert unmatched == ["/t/Wall_Unknown.tiff"]


def test_push_recent_folder_dedupes_reorders_and_caps(core_module):
    recent = ["/a", "/b", "/c", "/d", "/e"]
    updated = core_module.push_recent_folder(recent, "/c")
    assert updated[0] == "/c"
    assert updated.count("/c") == 1
    assert len(updated) == core_module.MAX_RECENT_FOLDERS


def test_compute_matches_respects_threshold(core_module):
    results = core_module.compute_matches(["Character"], ["Character", "Prop"], threshold=0.9)
    _obj_base, tex_base, score = results[0]
    assert tex_base == "Character"
    assert score >= 0.9


def test_compute_matches_returns_none_below_threshold(core_module):
    results = core_module.compute_matches(["Zzz"], ["Character"], threshold=0.9)
    _obj_base, tex_base, _score = results[0]
    assert tex_base is None


def test_similarity_never_raises_with_or_without_rapidfuzz(core_module):
    score = core_module.similarity("Character", "Character")
    assert 0.0 <= score <= 1.0
    assert score > 0.9
