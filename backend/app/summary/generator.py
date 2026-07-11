from app.core.models import CallSummary, Segment, Speaker


class SummaryGenerator:
    def generate(self, segments: list[Segment]) -> CallSummary:
        text = " ".join(segment.text for segment in segments)
        customer_needs: list[str] = []
        follow_up_items: list[str] = []
        risk_points: list[str] = []
        sales_promises: list[str] = []

        if "价格" in text or "免费" in text:
            customer_needs.append("价格咨询")
        if "退款" in text:
            customer_needs.append("退款咨询")
        if "投诉" in text:
            risk_points.append("客户提及投诉")
        if "明天" in text and "跟进" in text:
            follow_up_items.append("明天跟进客户")

        for segment in segments:
            if segment.speaker == Speaker.sales and any(word in segment.text for word in ("承诺", "保证", "绝对")):
                sales_promises.append(segment.text)
            for hit in segment.sensitive_hits:
                risk_points.append(f"{hit.level.value}: {hit.word}")
            for hit in segment.compliance_hits:
                risk_points.append(f"{hit.level.value}: {hit.message}")

        next_steps = follow_up_items or ["复核通话摘要并安排下一步跟进"]
        return CallSummary(
            customer_needs=customer_needs,
            sales_promises=sales_promises,
            risk_points=risk_points,
            follow_up_items=follow_up_items,
            next_steps=next_steps,
        )
