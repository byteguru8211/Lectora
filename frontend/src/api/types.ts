export type LectureStatus = "queued" | "processing" | "ready" | "failed";

/** How the conspectus is generated. */
export type LlmMode = "api" | "local" | "offline";

export interface LlmModeInfo {
  mode: LlmMode;
  label: string;
  description: string;
  enabled: boolean;
  available: boolean;
  selectable: boolean;
  model: string;
  base_url: string;
  detail?: string | null;
  latency_ms?: number | null;
  extra?: Record<string, unknown>;
}

export interface User {
  id: string;
  name: string;
  email: string;
  role: "student" | "teacher";
  created_at: string | null;
}

export interface LectureCard {
  id: string;
  title: string;
  title_auto: boolean;
  description: string | null;
  subject: string | null;
  topic: string | null;
  visibility: "private" | "public";
  group_id: string | null;
  share_token: string | null;
  status: LectureStatus;
  stage: string | null;
  stage_label: string | null;
  progress: number;
  duration_sec: number;
  duration_label: string;
  resolution: string | null;
  thumbnail_url: string | null;
  source_type: "upload" | "url";
  source_url: string | null;
  asr_profile: "accurate" | "fast";
  asr_engine: "vosk" | "whisper";
  use_gpu: boolean;
  segment_count: number;
  chunk_count: number;
  word_count: number;
  view_count: number;
  search_hits: number;
  error_message: string | null;
  llm_model: string | null;
  llm_mode: LlmMode;
  llm_mode_used: LlmMode | null;
  keywords: string[];
  created_at: string | null;
  processed_at: string | null;
  processing_ms: number | null;
}

export interface VideoGroup {
  id: string;
  name: string;
  description: string | null;
  visibility: "private" | "public";
  share_token: string | null;
  video_count: number;
  created_at: string | null;
}

export interface Section {
  id: number;
  idx: number;
  title: string;
  summary: string | null;
  start_sec: number;
  end_sec: number;
  timestamp: string;
  duration_sec: number;
  key_points: string[];
  details: string | null;
}

export interface LectureDetail extends LectureCard {
  summary: string | null;
  sections: Section[];
  questions: string[];
  media_url: string;
  subtitles_url: string;
  updated_at: string | null;
}

export interface Segment {
  idx: number;
  start_sec: number;
  end_sec: number;
  timestamp: string;
  text: string;
}

export interface TranscriptResponse {
  lecture_id: string;
  duration_sec: number;
  language: string;
  segments: Segment[];
}

export interface Span {
  start: number;
  end: number;
}

export interface SearchHit {
  chunk_id: number;
  lecture: { id: string; title: string };
  start_sec: number;
  end_sec: number;
  timestamp: string;
  text: string;
  snippet: string;
  spans: Span[];
  scores: Record<string, number>;
}

export interface SearchResponse {
  query: string;
  scope: "lecture" | "course";
  results: SearchHit[];
  reranked: boolean;
  took_ms: number;
  candidates: number;
  limit: number;
}

export interface RagCitation {
  lecture_id: string;
  lecture_title: string;
  start_sec: number;
  end_sec: number;
  timestamp: string;
  text: string;
}

export interface QaMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  citations: RagCitation[];
  grounded: boolean;
  created_at: string | null;
}

export interface QaResponse {
  answer: QaMessage;
  question: QaMessage;
  llm_used: boolean;
  llm_mode?: LlmMode;
}

export interface SearchSuggestion {
  text: string;
  type: "lecture" | "section" | "history";
  lecture_id?: string;
  lecture_title?: string;
  start_sec?: number;
}

export interface HealthCheck {
  ok: boolean;
  detail?: string | null;
  issues?: string[];
  profiles?: Record<string, boolean>;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  checks: {
    database: HealthCheck;
    ffmpeg: HealthCheck;
    asr_models: HealthCheck;
    embeddings: HealthCheck;
    reranker: HealthCheck;
    llm: { enabled: boolean; available: boolean; base_url: string; model: string };
    url_import: HealthCheck;
  };
  took_ms: number;
}

export interface SystemInfo {
  acceleration: { cuda: boolean; cuda_device: string | null; nvenc: boolean };
  llm: {
    enabled: boolean;
    model: string;
    base_url: string;
    default_mode: LlmMode;
    modes: Record<LlmMode, LlmModeInfo>;
    labels: Record<LlmMode, string>;
  };
  llm_api?: {
    enabled: boolean;
    model: string;
    base_url: string;
    max_prompt_chars: number;
    session_prefix: string;
  };
}

export interface Stats {
  lectures: { total: number; ready: number; processing: number; failed: number };
  content: {
    duration_sec: number;
    duration_label: string;
    words: number;
    chunks: number;
    segments: number;
  };
  search: { total: number; today: number; recent_queries: string[] };
  queue: { pending: number };
  storage: { used_bytes: number; used_gb: number; free_gb: number | null };
  top_lectures: { id: string; title: string; views: number; duration_label: string }[];
}

export interface UploadResult extends LectureCard {
  job_id: number;
}

export type RecommendationMode = "personalized" | "trending" | "cold_start";

export interface RecommendationInfo {
  score: number;
  reason: string;
  matched_topics: string[];
  personalized: boolean;
}

export interface PublicLecture extends LectureCard {
  owner_name: string;
  group_name: string | null;
  recommendation?: RecommendationInfo;
}

export interface InterestChip {
  label: string;
  kind: "subject" | "topic" | "keyword";
  weight: number;
}

export interface RecommendationFeed {
  mode: RecommendationMode;
  fallback: boolean;
  interests: InterestChip[];
  items: PublicLecture[];
  generated_at: string | null;
}
