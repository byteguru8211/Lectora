export type LectureStatus = "queued" | "processing" | "ready" | "failed";

export interface LectureCard {
  id: string;
  title: string;
  title_auto: boolean;
  description: string | null;
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
  segment_count: number;
  chunk_count: number;
  word_count: number;
  view_count: number;
  search_hits: number;
  error_message: string | null;
  llm_model: string | null;
  keywords: string[];
  created_at: string | null;
  processed_at: string | null;
  processing_ms: number | null;
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
}

export interface LectureDetail extends LectureCard {
  summary: string | null;
  sections: Section[];
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
