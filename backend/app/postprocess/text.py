QUESTION_HINTS = ("吗", "呢", "么", "是不是", "能不能", "可以")


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\n", " ").split())


def add_basic_punctuation(text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return ""
    raw_parts = [part.strip() for part in normalized.split(" ") if part.strip()]
    parts: list[str] = []
    for part in raw_parts:
        if part[-1] in "。！？!?":
            parts.append(part.replace("!", "！").replace("?", "？"))
            continue
        mark = "？" if part.endswith(QUESTION_HINTS) else "。"
        parts.append(f"{part}{mark}")
    return "".join(parts)


def split_long_text(text: str, max_chars: int = 80) -> list[str]:
    if len(text) <= max_chars:
        return [text] if text else []

    sentences: list[str] = []
    buffer = ""
    for char in text:
        buffer += char
        if char in "。！？":
            sentences.append(buffer)
            buffer = ""
    if buffer:
        sentences.append(buffer)

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        chunks.append(current)
    return chunks
