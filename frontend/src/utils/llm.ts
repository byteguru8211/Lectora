import type { LlmMode, NotesModeUsed } from "../api/types";

/** UI copy and ordering for the two selectable notes modes. */
export const LLM_MODES: LlmMode[] = ["api", "local"];

export const LLM_MODE_META: Record<LlmMode, { label: string; short: string; description: string }> = {
  api: {
    label: "DeepSeek API",
    short: "API",
    description: "Максимально подробный конспект: больше разделов, тезисов и деталей.",
  },
  local: {
    label: "Локальная модель",
    short: "Локально",
    description: "Qwen на этом компьютере: без интернета, компактнее и быстрее.",
  },
};

const STORAGE_KEY = "lectora-llm-mode";

export function isLlmMode(value: unknown): value is LlmMode {
  return value === "api" || value === "local";
}

export function readStoredLlmMode(fallback: LlmMode = "api"): LlmMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return isLlmMode(stored) ? stored : fallback;
  } catch {
    return fallback;
  }
}

export function storeLlmMode(mode: LlmMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* private mode — the choice just is not remembered */
  }
}

export function llmModeLabel(mode: NotesModeUsed | null | undefined, styles: "full" | "short" = "full"): string {
  if (!mode) return "—";
  if (mode === "offline") return styles === "short" ? "Фолбэк" : "Без ИИ (аварийный фолбэк)";
  return styles === "short" ? LLM_MODE_META[mode].short : LLM_MODE_META[mode].label;
}
