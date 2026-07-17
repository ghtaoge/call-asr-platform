export type Speaker = "sales" | "customer" | "unknown";
export type RiskLevel = "low" | "medium" | "high" | "critical";
export type JobStatus = "queued" | "running" | "completed" | "failed" | "interrupted";
export type JobStage =
  | "queued"
  | "preparing_audio"
  | "transcribing_sales"
  | "transcribing_customer"
  | "merging_segments"
  | "analyzing_emotion"
  | "scanning_risks"
  | "generating_summary"
  | "completed"
  | "failed";
export type SummaryStatus = "pending" | "running" | "completed" | "failed";

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

export interface ComplianceHit {
  rule_id: string;
  level: RiskLevel;
  message: string;
  suggestion: string;
  segment_id: string;
}

export interface Segment {
  id: string;
  session_id: string;
  speaker: Speaker;
  start_ms: number;
  end_ms: number;
  text: string;
  translation: string;
  language: string;
  target_language: string;
  emotion: { label: string; confidence: number; score: number };
  sensitive_hits: SensitiveHit[];
  compliance_hits: ComplianceHit[];
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
  overview: string;
  customer_needs: string[];
  sales_promises: string[];
  risk_points: string[];
  follow_up_items: string[];
  next_steps: string[];
}

export interface JobCreateResponse {
  job_id: string;
  session_id: string;
  status: JobStatus;
  stage: JobStage;
  progress: number;
}

export interface JobStatusResponse extends JobCreateResponse {
  summary_status: SummaryStatus;
  error_code?: string;
  error_message?: string;
}

export interface AnalysisResult {
  job_id: string;
  session_id: string;
  summary_status: SummaryStatus;
  summary_error_code?: string;
  segments: Segment[];
  quality: QualityScore;
  summary?: CallSummary;
}
