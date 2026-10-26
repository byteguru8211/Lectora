import type {
  HealthResponse,
  LectureCard,
  LectureDetail,
  QaMessage,
  QaResponse,
  SearchResponse,
  SearchSuggestion,
  Stats,
  TranscriptResponse,
  UploadResult,
  User,
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
}

export const api = {
  me: () => request<{ user: User }>("/api/auth/me"),
  register: (name: string, email: string, password: string) => request<{ user: User }>("/api/auth/register", { method: "POST", body: JSON.stringify({ name, email, password }) }),
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

  reprocess: (id: string, asrProfile?: string) =>
    request<LectureCard & { job_id: number }>(`/api/lectures/${id}/reprocess`, {
      method: "POST",
      body: JSON.stringify({ asr_profile: asrProfile }),
    }),

  importUrl: (url: string, title?: string, asrProfile: "accurate" | "fast" = "accurate") =>
    request<UploadResult>("/api/lectures/import", {
      method: "POST",
      body: JSON.stringify({ url, title, asr_profile: asrProfile }),
    }),

  health: () => request<HealthResponse>("/api/health"),
  stats: () => request<Stats>("/api/stats"),
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
