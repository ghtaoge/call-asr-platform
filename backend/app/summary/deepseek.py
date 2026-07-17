import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.models import CallSummary, Segment, Speaker


class SummaryError(RuntimeError):
    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


class DeepSeekSummaryProvider:
    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_chunk_chars: int = 12_000,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.transport = transport
        self.max_chunk_chars = max_chunk_chars

    async def generate(self, segments: list[Segment]) -> CallSummary:
        if not self.api_key:
            raise SummaryError("summary_missing_api_key", "未配置 DeepSeek API Key")
        lines = [self._segment_line(segment) for segment in segments if segment.text.strip()]
        if not lines:
            return CallSummary(overview="未识别到有效通话内容")
        chunks = self._chunks(lines)
        if len(chunks) == 1:
            return await self._request_summary(chunks[0], final=True)
        partials = [await self._request_summary(chunk, final=False) for chunk in chunks]
        combined = "\n".join(summary.model_dump_json() for summary in partials)
        return await self._request_summary(combined, final=True)

    def _chunks(self, lines: list[str]) -> list[str]:
        chunks: list[str] = []
        current: list[str] = []
        size = 0
        for line in lines:
            if current and size + len(line) + 1 > self.max_chunk_chars:
                chunks.append("\n".join(current))
                current = []
                size = 0
            current.append(line)
            size += len(line) + 1
        if current:
            chunks.append("\n".join(current))
        return chunks

    async def _request_summary(self, transcript: str, final: bool) -> CallSummary:
        instruction = (
            "你是中文客服通话质检助手。只依据输入事实总结，不得编造订单、金额、承诺或处理结果。"
            "返回一个 JSON 对象，字段必须为 overview、customer_needs、sales_promises、risk_points、"
            "follow_up_items、next_steps；overview 是简短中文结论，其余字段都是中文字符串数组。"
        )
        if not final:
            instruction += "这是通话的一部分，只提取该部分明确出现的事实。"
        content = await self._chat(instruction, transcript)
        try:
            return self._parse(content)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            repair = (
                "下面的模型输出不符合要求。只返回修复后的 JSON 对象，不要代码围栏或解释。\n"
                f"错误：{exc}\n原输出：{content}"
            )
            repaired = await self._chat(instruction, repair)
            try:
                return self._parse(repaired)
            except (json.JSONDecodeError, ValidationError, ValueError) as final_exc:
                raise SummaryError("summary_invalid_response", "DeepSeek 摘要格式无效") from final_exc

    async def _chat(self, system: str, user: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "temperature": 0.1,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                headers=headers,
            ) as client:
                response = await client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise SummaryError("summary_timeout", "DeepSeek 摘要生成超时") from exc
        except httpx.HTTPError as exc:
            raise SummaryError("summary_failed", "无法连接 DeepSeek 摘要服务") from exc
        if response.status_code == 429:
            raise SummaryError("summary_rate_limited", "DeepSeek 请求过于频繁，请稍后重试")
        if response.is_error:
            raise SummaryError("summary_failed", f"DeepSeek 返回 {response.status_code}")
        try:
            data: dict[str, Any] = response.json()
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise SummaryError("summary_invalid_response", "DeepSeek 返回结构无效") from exc

    @staticmethod
    def _parse(content: str) -> CallSummary:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            cleaned = cleaned[first_newline + 1 :] if first_newline >= 0 else cleaned
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        summary = CallSummary.model_validate(json.loads(cleaned.strip()))
        summary.overview = summary.overview.strip()[:400]
        for name in (
            "customer_needs",
            "sales_promises",
            "risk_points",
            "follow_up_items",
            "next_steps",
        ):
            values = [str(value).strip()[:200] for value in getattr(summary, name) if str(value).strip()]
            setattr(summary, name, values[:10])
        return summary

    @staticmethod
    def _segment_line(segment: Segment) -> str:
        role = "销售" if segment.speaker == Speaker.sales else "客户"
        start = segment.start_ms / 1000
        end = segment.end_ms / 1000
        return f"[{start:.3f}-{end:.3f}][{role}] {segment.text.strip()}"
