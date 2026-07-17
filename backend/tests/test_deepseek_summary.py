import httpx
import pytest

from app.core.models import Segment, Speaker
from app.summary.deepseek import DeepSeekSummaryProvider, SummaryError


def segments():
    return [
        Segment(
            id="c1",
            session_id="call_1",
            speaker=Speaker.customer,
            start_ms=1000,
            end_ms=2500,
            text="我要退款。",
        )
    ]


async def test_deepseek_returns_validated_structured_summary():
    payload = (
        '{"overview":"客户要求退款","customer_needs":["退款"],'
        '"sales_promises":[],"risk_points":[],"follow_up_items":["核对订单"],'
        '"next_steps":["回电"]}'
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": payload}}]},
        )
    )
    provider = DeepSeekSummaryProvider(
        "key",
        "https://api.deepseek.com",
        "deepseek-v4-pro",
        transport=transport,
    )
    summary = await provider.generate(segments())
    assert summary.overview == "客户要求退款"
    assert summary.customer_needs == ["退款"]


async def test_missing_api_key_is_a_summary_only_error():
    provider = DeepSeekSummaryProvider(None, "https://api.deepseek.com", "deepseek-v4-pro")
    with pytest.raises(SummaryError) as exc:
        await provider.generate(segments())
    assert exc.value.code == "summary_missing_api_key"


async def test_invalid_json_is_repaired_once():
    calls = 0
    valid = '{"overview":"已修复","customer_needs":[],"sales_promises":[],"risk_points":[],"follow_up_items":[],"next_steps":[]}'

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        content = "not-json" if calls == 1 else valid
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    provider = DeepSeekSummaryProvider(
        "key",
        "https://api.deepseek.com",
        "deepseek-v4-pro",
        transport=httpx.MockTransport(handler),
    )
    assert (await provider.generate(segments())).overview == "已修复"
    assert calls == 2
