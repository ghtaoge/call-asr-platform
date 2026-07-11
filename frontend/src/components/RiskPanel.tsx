import { ShieldAlert } from "lucide-react";
import type { CallSummary, QualityScore, Segment } from "../types";

interface Props {
  segments: Segment[];
  quality?: QualityScore;
  summary?: CallSummary;
}

export function RiskPanel({ segments, quality, summary }: Props) {
  const risks = segments.flatMap((segment) => [
    ...segment.sensitive_hits.map((hit) => `${hit.level}: ${hit.word}（${segment.speaker}）`),
    ...segment.compliance_hits.map((hit) => `${hit.level}: ${hit.message}`)
  ]);

  return (
    <aside className="risk" aria-label="风险与质检">
      <h2>
        <ShieldAlert size={18} /> 风险与质检
      </h2>
      {quality && <div className="score">{quality.score}</div>}
      {risks.length === 0 ? (
        <p className="empty">暂无风险命中。</p>
      ) : (
        <ul className="riskList">
          {risks.map((risk, index) => (
            <li key={`${risk}-${index}`}>{risk}</li>
          ))}
        </ul>
      )}
      {summary && (
        <section className="summary">
          <h3>摘要</h3>
          <p>客户诉求：{summary.customer_needs.join("、") || "未识别"}</p>
          <p>待跟进：{summary.follow_up_items.join("、") || "暂无"}</p>
          <p>下一步：{summary.next_steps.join("、")}</p>
        </section>
      )}
    </aside>
  );
}
