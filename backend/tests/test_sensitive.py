from app.core.models import RiskLevel, Speaker
from app.sensitive.automaton import SensitiveEntry, SensitiveScanner


def test_scanner_finds_multiple_levels_in_one_pass():
    scanner = SensitiveScanner.from_entries(
        [
            SensitiveEntry(word="绝对有效", level=RiskLevel.critical, category="promise"),
            SensitiveEntry(word="免费", level=RiskLevel.medium, category="price"),
        ]
    )

    hits = scanner.scan(
        text="这个方案绝对有效，而且今天免费。",
        speaker=Speaker.sales,
        segment_id="seg_1",
        start_ms=1000,
        end_ms=3000,
    )

    assert [hit.word for hit in hits] == ["绝对有效", "免费"]
    assert hits[0].level == RiskLevel.critical
    assert hits[0].context == "这个方案绝对有效，而且"


def test_scanner_prefers_longer_overlapping_word():
    scanner = SensitiveScanner.from_entries(
        [
            SensitiveEntry(word="有效", level=RiskLevel.high, category="promise"),
            SensitiveEntry(word="绝对有效", level=RiskLevel.critical, category="promise"),
        ]
    )

    hits = scanner.scan("绝对有效", Speaker.sales, "seg_1", 0, 1000)

    assert len(hits) == 1
    assert hits[0].word == "绝对有效"
