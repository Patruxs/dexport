from dexport.util import human_bytes, is_snowflake, normalize, strip_diacritics


def test_strip_diacritics_vietnamese():
    assert strip_diacritics("cú đêm") == "cu dem"
    assert strip_diacritics("lười-chat-tổng") == "luoi-chat-tong"
    assert strip_diacritics("Đường") == "Duong"


def test_normalize_casefold_and_whitespace():
    assert normalize("  Cú   Đêm  ") == "cu dem"
    assert normalize("LƯỜI") == "luoi"
    assert normalize(None) == ""
