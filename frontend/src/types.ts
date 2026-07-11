export type Speaker = "sales" | "customer" | "unknown";
export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface SensitiveHit {
  word: string;
  level: RiskLevel;
  category: string;
  start: number;
  end: number;
  context: string;
  speaker: Speaker;
  segment_id: string;
  start_ms: number;
  end_ms: number;
}

export interface Segment {
  id: string;
  session_id: string;
  speaker: Speaker;
  start_ms: number;
  end_ms: number;
  text: string;
  translation: string;
  emotion: { label: string; score: number };
  sensitive_hits: SensitiveHit[];
  compliance_hits: Array<{ rule_id: string; level: RiskLevel; message: string; suggestion: string }>;
  confidence: number;
  is_final: boolean;
}

export interface QualityScore {
  score: number;
  noise_level: "low" | "medium" | "high";
  silence_ratio: number;
  sales_talk_ratio: number;
  customer_talk_ratio: number;
  interruptions: number;
  negative_emotion_ratio: number;
  risk_hit_count: number;
  suggestions: string[];
}

export interface CallSummary {
  customer_needs: string[];
  sales_promises: string[];
  risk_points: string[];
  follow_up_items: string[];
  next_steps: string[];
}
