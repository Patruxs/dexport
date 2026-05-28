from dexport.util import human_bytes, is_snowflake, normalize, strip_diacritics


def test_strip_diacritics_vietnamese():
    assert strip_diacritics("cú đêm") == "cu dem"
    assert strip_diacritics("lười-chat-tổng") == "luoi-chat-tong"
    assert strip_diacritics("Đường") == "Duong"


def test_normalize_casefold_and_whitespace():
    assert normalize("  Cú   Đêm  ") == "cu dem"
    assert normalize("LƯỜI") == "luoi"
    assert normalize(None) == ""


def test_normalize_equal_across_diacritics():
    assert normalize("cu dem") == normalize("cú đêm")


def test_is_snowflake():
    assert is_snowflake("123456789012345678")  # 18 digits
    assert is_snowflake("12345678901234567")  # 17 digits
    assert not is_snowflake("12345")
    assert not is_snowflake("not-a-number")
    assert not is_snowflake("")
    # An all-numeric channel/guild NAME must not be mistaken for an ID.
    assert not is_snowflake("1234567890123456")  # 16 digits
    assert not is_snowflake("1" * 21)  # too long


def test_human_bytes():
    assert human_bytes(512) == "512B"
    assert human_bytes(1536).endswith("KB")
    assert human_bytes(5 * 1024 * 1024).endswith("MB")
