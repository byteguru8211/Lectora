import type {
  HealthResponse,
  LectureCard,
  LectureDetail,
  LlmMode,
  QaMessage,
  QaResponse,
  SearchResponse,
  SearchSuggestion,
  Stats,
  TranscriptResponse,
  UploadResult,
  User,
  SystemInfo,
  VideoGroup,
  RecommendationFeed,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code = "error") {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
    ...init,
  });
  if (!response.ok) {
    let message = `Ошибка запроса (${response.status})`;
    let code = "http_error";
    try {
      const data = await response.json();
      if (data?.error?.message) message = data.error.message;
      if (data?.error?.code) code = data.error.code;
    } catch {
      /* not JSON */
    }
    throw new ApiError(message, response.status, code);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface UploadPayload {
  file: File;
  title?: string;
  description?: string;
  asrProfile: "accurate" | "fast";
  asrEngine: "vosk" | "whisper";
  useGpu: boolean;
  visibility: "private" | "public";
  groupId?: string;
  llmMode: LlmMode;
}

export const api = {
  me: () => request<{ user: User }>("/api/auth/me"),
  register: (name: string, email: string, password: string, role: "student" | "teacher") => request<{ user: User }>("/api/auth/register", { method: "POST", body: JSON.stringify({ name, email, password, role }) }),
  login: (email: string, password: string) => request<{ user: User }>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  lectures: (params: { status?: string; q?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.status) query.set("status", params.status);
    if (params.q) query.set("q", params.q);
    if (params.limit) query.set("limit", String(params.limit));
    return request<{ items: LectureCard[]; total: number }>(`/api/lectures?${query}`);
  },

  lecture: (id: string) => request<LectureDetail>(`/api/lectures/${id}`),

  transcript: (id: string) => request<TranscriptResponse>(`/api/lectures/${id}/transcript`),

  status: (id: string) =>
    request<{
      id: string;
      status: string;
      stage: string | null;
      stage_label: string | null;
      progress: number;
      error_message: string | null;
    }>(`/api/lectures/${id}/status`),

  search: (q: string, lectureId?: string, limit = 15) => {
    const query = new URLSearchParams({ q, limit: String(limit) });
    if (lectureId) query.set("lecture_id", lectureId);
    return request<SearchResponse>(`/api/search?${query}`);
  },

  suggest: (q: string) =>
    request<{ items: SearchSuggestion[] }>(`/api/search/suggest?q=${encodeURIComponent(q)}`),

  qaHistory: (id: string) => request<{ items: QaMessage[] }>(`/api/lectures/${id}/qa`),

  ask: (id: string, question: string) =>
    request<QaResponse>(`/api/lectures/${id}/qa`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  updateLecture: (id: string, patch: { title?: string; description?: string; subject?: string | null; topic?: string | null }) =>
    request<LectureCard>(`/api/lectures/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteLecture: (id: string) =>
    request<void>(`/api/lectures/${id}`, { method: "DELETE" }),

  reprocess: (id: string, options: { asrProfile?: string; llmMode?: LlmMode } = {}) =>
    request<LectureCard & { job_id: number }>(`/api/lectures/${id}/reprocess`, {
      method: "POST",
      body: JSON.stringify({ asr_profile: options.asrProfile, llm_mode: options.llmMode }),
    }),

  /** Rebuild only the conspectus (transcript and index are kept). */
  regenerateNotes: (id: string, llmMode?: LlmMode) =>
    request<LectureCard & { job_id: number }>(`/api/lectures/${id}/notes`, {
      method: "POST",
      body: JSON.stringify({ llm_mode: llmMode }),
    }),

  importUrl: (url: string, title?: string, asrProfile: "accurate" | "fast" = "accurate", useGpu = false, asrEngine: "vosk" | "whisper" = "vosk", visibility: "private" | "public" = "private", groupId?: string, llmMode: LlmMode = "api") =>
    request<UploadResult>("/api/lectures/import", {
      method: "POST",
      body: JSON.stringify({ url, title, asr_profile: asrProfile, use_gpu: useGpu, asr_engine: asrEngine, visibility, group_id: groupId, llm_mode: llmMode }),
    }),

  health: () => request<HealthResponse>("/api/health"),
  systemInfo: () => request<SystemInfo>("/api/system/info"),
  stats: () => request<Stats>("/api/stats"),
  groups: () => request<{ items: VideoGroup[] }>("/api/groups"),
  createGroup: (name: string, visibility: "private" | "public") => request<VideoGroup>("/api/groups", { method: "POST", body: JSON.stringify({ name, visibility }) }),
  shareLecture: (id: string) => request<{ token: string; path: string }>(`/api/lectures/${id}/share`, { method: "POST" }),
  shareGroup: (id: string) => request<{ token: string; path: string }>(`/api/groups/${id}/share`, { method: "POST" }),
  publicLectures: () => request<{ items: (LectureCard & { owner_name: string; group_name: string | null })[] }>("/api/public/lectures"),
  recommendations: (limit = 12) => request<RecommendationFeed>(`/api/recommendations?limit=${limit}`),
  recordPublicView: (id: string) =>
    request<{ tracked: boolean; view_count: number; first_view: boolean }>(`/api/public/lectures/${id}/view`, { method: "POST" }),
  publicLecture: (id: string) => request<LectureDetail>(`/api/public/lectures/${id}`),
  sharedVideo: (token: string) => request<LectureDetail>(`/api/shared/videos/${token}`),
  sharedGroup: (token: string) => request<{ group: VideoGroup; items: LectureCard[] }>(`/api/shared/groups/${token}`),
  sharedGroupLecture: (token: string, id: string) => request<LectureDetail>(`/api/shared/groups/${token}/lectures/${id}`),
  accessTranscript: (base: string) => request<TranscriptResponse>(`${base}/transcript`),
  accessLecture: (base: string) => request<LectureDetail>(base),
  accessSearch: (base: string, q: string, limit = 12) => request<SearchResponse>(`${base}/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  accessQa: (base: string, question: string) => request<QaResponse>(`${base}/qa`, { method: "POST", body: JSON.stringify({ question }) }),
};

/** Upload with real progress events (XHR is still the only way to get them). */
export function uploadLecture(
  payload: UploadPayload,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", payload.file);
    if (payload.title) form.append("title", payload.title);
    if (payload.description) form.append("description", payload.description);
    form.append("asr_profile", payload.asrProfile);
    form.append("asr_engine", payload.asrEngine);
    form.append("use_gpu", String(payload.useGpu));
    form.append("visibility", payload.visibility);
    if (payload.groupId) form.append("group_id", payload.groupId);
    form.append("llm_mode", payload.llmMode);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/lectures");
    xhr.responseType = "json";

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      const body = xhr.response ?? safeParse(xhr.responseText);
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as UploadResult);
      } else {
        reject(
          new ApiError(
            body?.error?.message ?? "Не удалось загрузить файл",
            xhr.status,
            body?.error?.code ?? "upload_failed",
          ),
        );
      }
    };
    xhr.onerror = () => reject(new ApiError("Сеть недоступна", 0, "network"));
    xhr.onabort = () => reject(new ApiError("Загрузка отменена", 0, "aborted"));

    if (signal) {
      signal.addEventListener("abort", () => xhr.abort());
    }
    xhr.send(form);
  });
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** SSE subscription for processing progress; returns a disposer. */
export function subscribeProgress(
  lectureId: string,
  onUpdate: (payload: {
    status: string;
    stage: string | null;
    stage_label: string | null;
    progress: number;
    error_message: string | null;
  }) => void,
): () => void {
  const source = new EventSource(`/api/lectures/${lectureId}/events`);
  const handle = (event: MessageEvent) => {
    try {
      onUpdate(JSON.parse(event.data));
    } catch {
      /* ignore malformed frame */
    }
  };
  source.addEventListener("progress", handle as EventListener);
  source.addEventListener("done", ((event: MessageEvent) => {
    handle(event);
    source.close();
  }) as EventListener);
  source.onerror = () => source.close();
  return () => source.close();
}
