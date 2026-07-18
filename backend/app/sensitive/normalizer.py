from __future__ import annotations

from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True, slots=True)
class NormalizedText:
    text: str
    source_indices: tuple[int, ...]

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        if start < 0 or end <= start or end > len(self.source_indices):
            raise ValueError("normalized span is out of bounds")
        indices = self.source_indices[start:end]
        return min(indices), max(indices) + 1


def normalize_with_mapping(value: str) -> NormalizedText:
    chars: list[str] = []
    indices: list[int] = []
    for index, original in enumerate(value):
        normalized = unicodedata.normalize("NFKC", original).casefold()
        for char in normalized:
            if unicodedata.category(char).startswith("Z") or char.isspace():
                continue
            chars.append(char)
            indices.append(index)
    return NormalizedText("".join(chars), tuple(indices))


def normalize_word(value: str, *, max_length: int = 128) -> str:
    normalized = normalize_with_mapping(value).text
    if not normalized:
        raise ValueError("敏感词不能为空")
    if len(normalized) > max_length:
        raise ValueError(f"敏感词最多 {max_length} 个字符")
    return normalized
