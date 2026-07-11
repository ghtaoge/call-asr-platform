from collections import deque
from dataclasses import dataclass, field

from app.core.models import RiskLevel, SensitiveHit, Speaker


@dataclass(frozen=True)
class SensitiveEntry:
    word: str
    level: RiskLevel
    category: str
    enabled: bool = True


@dataclass
class _Node:
    children: dict[str, int] = field(default_factory=dict)
    fail: int = 0
    outputs: list[SensitiveEntry] = field(default_factory=list)


class SensitiveScanner:
    def __init__(self, nodes: list[_Node]) -> None:
        self._nodes = nodes

    @classmethod
    def from_entries(cls, entries: list[SensitiveEntry]) -> "SensitiveScanner":
        nodes = [_Node()]
        for entry in entries:
            if not entry.enabled or not entry.word:
                continue
            current = 0
            for char in entry.word:
                next_node = nodes[current].children.get(char)
                if next_node is None:
                    next_node = len(nodes)
                    nodes[current].children[char] = next_node
                    nodes.append(_Node())
                current = next_node
            nodes[current].outputs.append(entry)

        queue: deque[int] = deque()
        for child in nodes[0].children.values():
            queue.append(child)
            nodes[child].fail = 0

        while queue:
            current = queue.popleft()
            for char, child in nodes[current].children.items():
                queue.append(child)
                fail = nodes[current].fail
                while fail and char not in nodes[fail].children:
                    fail = nodes[fail].fail
                nodes[child].fail = nodes[fail].children.get(char, 0)
                nodes[child].outputs.extend(nodes[nodes[child].fail].outputs)

        return cls(nodes)

    def scan(
        self,
        text: str,
        speaker: Speaker,
        segment_id: str,
        start_ms: int,
        end_ms: int,
    ) -> list[SensitiveHit]:
        raw_hits: list[SensitiveHit] = []
        state = 0
        for index, char in enumerate(text):
            while state and char not in self._nodes[state].children:
                state = self._nodes[state].fail
            state = self._nodes[state].children.get(char, 0)
            for entry in self._nodes[state].outputs:
                start = index - len(entry.word) + 1
                raw_hits.append(
                    SensitiveHit(
                        word=entry.word,
                        level=entry.level,
                        category=entry.category,
                        start=start,
                        end=index + 1,
                        context=_context(text, start, index + 1),
                        speaker=speaker,
                        segment_id=segment_id,
                        start_ms=start_ms,
                        end_ms=end_ms,
                    )
                )
        return _remove_overlaps(raw_hits)


def _context(text: str, start: int, end: int, left_radius: int = 4, right_radius: int = 3) -> str:
    return text[max(0, start - left_radius) : min(len(text), end + right_radius)]


def _remove_overlaps(hits: list[SensitiveHit]) -> list[SensitiveHit]:
    ordered = sorted(hits, key=lambda hit: (hit.start, -(hit.end - hit.start)))
    selected: list[SensitiveHit] = []
    occupied: set[int] = set()
    for hit in ordered:
        span = set(range(hit.start, hit.end))
        if occupied.intersection(span):
            continue
        selected.append(hit)
        occupied.update(span)
    return sorted(selected, key=lambda hit: hit.start)
