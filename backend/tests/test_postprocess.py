from app.postprocess.text import add_basic_punctuation, split_long_text


def test_add_basic_punctuation_adds_sentence_marks():
    text = "您好我是顾问 我想了解您的需求 可以说一下吗"

    result = add_basic_punctuation(text)

    assert result == "您好我是顾问。我想了解您的需求。可以说一下吗？"


def test_split_long_text_keeps_chunks_under_limit():
    text = "第一句很短。第二句也很短。第三句内容稍微长一点。第四句结束。"

    chunks = split_long_text(text, max_chars=16)

    assert chunks == ["第一句很短。第二句也很短。", "第三句内容稍微长一点。", "第四句结束。"]
