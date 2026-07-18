from app.sensitive.normalizer import normalize_with_mapping, normalize_word


def test_normalizer_maps_nfkc_case_and_whitespace_to_original_span():
    value = normalize_with_mapping("请联系 Ａ B C 客服")
    assert value.text == "请联系abc客服"
    start = value.text.index("abc")
    assert value.original_span(start, start + 3) == (4, 9)


def test_normalizer_keeps_traditional_and_homophones_exact():
    assert normalize_word("退貨") == "退貨"
    assert normalize_word("微心") == "微心"
