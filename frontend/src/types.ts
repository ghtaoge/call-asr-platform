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
export type ModuleStatus = "pending" | "running" | "completed" | "failed";
export type SummaryStatus = ModuleStatus;

export interface ModuleError {
  code: string;
  message: string;
}

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
  speaker_cluster?: "speaker_1" | "speaker_2";
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
  transcript_status: ModuleStatus;
  emotion_status: ModuleStatus;
  risk_status: ModuleStatus;
  quality_status: ModuleStatus;
  summary_status: SummaryStatus;
  module_errors: Record<string, ModuleError>;
  error_code?: string;
  error_message?: string;
}

export interface AnalysisResult {
  job_id: string;
  session_id: string;
  transcript_status: ModuleStatus;
  emotion_status: ModuleStatus;
  risk_status: ModuleStatus;
  quality_status: ModuleStatus;
  summary_status: SummaryStatus;
  module_errors: Record<string, ModuleError>;
  segments: Segment[];
  quality?: QualityScore;
  summary?: CallSummary;
}

export type TtsJobStatus = "queued" | "running" | "completed" | "failed" | "expired";

export interface TtsVoiceResponse {
  voice_id: string;
  prompt_text: string;
  expires_at: string;
}

export interface TtsPresetVoice {
  id: string;
  voice_id: string;
  label: string;
  language: string;
  gender: "female" | "male";
}

export interface TtsHealth {
  status: "starting" | "ready" | "busy" | "unavailable";
  model?: string;
  queue_depth: number;
  error_code?: string;
  fallback_available: boolean;
  message: string;
  checked_at: string;
}

export interface TtsJobResponse {
  job_id: string;
  voice_id: string;
  status: TtsJobStatus;
  error_code?: string;
  error_message?: string;
}
