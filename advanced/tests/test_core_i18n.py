"""
Tests for the shared EN/ES translation table. Both front-ends (Maya,
Blender) call core.tr()/core.other_language() instead of keeping their
own copies — these tests are what keeps the two UIs from silently
drifting out of sync (e.g. one adding a key the other never gets).
"""
import re


def test_tr_returns_english_by_default(core_module):
    assert core_module.tr("en", "btn_smart_match") == "◉  SMART MATCH"


def test_tr_returns_spanish_when_requested(core_module):
    assert "MATCH" in core_module.tr("es", "btn_smart_match")


def test_tr_falls_back_to_default_language_for_unknown_language_code(core_module):
    assert core_module.tr("fr", "btn_smart_match") == core_module.tr("en", "btn_smart_match")


def test_tr_falls_back_to_key_itself_for_unknown_key(core_module):
    assert core_module.tr("en", "this_key_does_not_exist") == "this_key_does_not_exist"


def test_tr_formats_placeholders(core_module):
    text = core_module.tr("en", "match_status", matched=3, total=5)
    assert text == "3 / 5 objects matched"


def test_other_language_toggles_between_en_and_es(core_module):
    assert core_module.other_language("en") == "es"
    assert core_module.other_language("es") == "en"


def test_translation_tables_have_matching_keys(core_module):
    """Si un idioma tiene una key que el otro no tiene, la UI de ese
    idioma se queda mostrando el texto en inglés (fallback silencioso) —
    este test evita que eso pase desapercibido."""
    en_keys = set(core_module.TRANSLATIONS["en"].keys())
    es_keys = set(core_module.TRANSLATIONS["es"].keys())
    assert en_keys == es_keys, f"Key mismatch: {en_keys ^ es_keys}"


def test_translation_placeholders_match_between_languages(core_module):
    """Cada key con placeholders "{...}" debe tener los MISMOS placeholders
    en los dos idiomas — si no, tr(..., **kwargs) revienta sólo en uno de
    los dos idiomas al pasarle los kwargs reales que usa la UI."""
    placeholder_re = re.compile(r'\{(\w+)\}')
    en = core_module.TRANSLATIONS["en"]
    es = core_module.TRANSLATIONS["es"]
    for key in en:
        en_placeholders = set(placeholder_re.findall(en[key]))
        es_placeholders = set(placeholder_re.findall(es.get(key, "")))
        assert en_placeholders == es_placeholders, (
            f"Placeholder mismatch for key '{key}': "
            f"en={en_placeholders} es={es_placeholders}")
