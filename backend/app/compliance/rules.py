from app.core.models import ComplianceHit, RiskLevel, Segment


class ComplianceRuleEngine:
    def check(self, segment: Segment) -> list[ComplianceHit]:
        hits: list[ComplianceHit] = []
        rules = [
            ("absolute_promise", ("绝对", "肯定", "百分百"), RiskLevel.critical, "避免绝对化承诺", "改为说明可能效果和限制条件"),
            ("income_promise", ("保证赚钱", "稳赚", "收益保证"), RiskLevel.high, "避免收益保证", "提供客观风险说明"),
            ("pressure_sale", ("今天不买", "马上失效", "最后机会"), RiskLevel.medium, "避免过度催促成交", "给客户充分决策时间"),
            ("complaint_no_empathy", ("投诉", "没人管"), RiskLevel.high, "投诉场景需及时安抚", "先安抚客户情绪，再确认处理方案"),
        ]
        for rule_id, keywords, level, message, suggestion in rules:
            if any(keyword in segment.text for keyword in keywords):
                hits.append(
                    ComplianceHit(
                        rule_id=rule_id,
                        level=level,
                        message=message,
                        suggestion=suggestion,
                        segment_id=segment.id,
                    )
                )
        return hits
