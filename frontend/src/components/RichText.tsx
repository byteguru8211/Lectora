import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";

interface Props {
  text: string;
  className?: string;
}

interface FormulaProps {
  tex: string;
  block?: boolean;
}

type KatexLike = {
  render: (tex: string, element: HTMLElement, options?: Record<string, unknown>) => void;
};

let katexLoader: Promise<KatexLike> | null = null;

function loadKatex(): Promise<KatexLike> {
  if (!katexLoader) {
    katexLoader = import("katex").then(
      (module) => ((module as { default?: unknown }).default ?? module) as KatexLike,
    );
  }
  return katexLoader;
}

/**
 * KaTeX is loaded on first formula, so lectures without maths do not pay for
 * it. Rendering happens into a ref (no `dangerouslySetInnerHTML`) with
 * `trust: false`, which disables `\href` and other escape hatches.
 */
export function MathFormula({ tex, block = false }: FormulaProps) {
  const host = useRef<HTMLSpanElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");

  useEffect(() => {
    let alive = true;
    setState("loading");
    if (host.current) host.current.textContent = "";
    loadKatex()
      .then((katex) => {
        if (!alive || !host.current) return;
        try {
          katex.render(tex, host.current, {
            displayMode: block,
            throwOnError: false,
            strict: false,
            trust: false,
            output: "htmlAndMathml",
          });
          setState("ready");
        } catch {
          setState("failed");
        }
      })
      .catch(() => {
        if (alive) setState("failed");
      });
    return () => {
      alive = false;
    };
  }, [tex, block]);

  return (
    <span className={`rt-math ${block ? "rt-math--block" : ""}`.trim()}>
      <span ref={host} className="rt-math__body" hidden={state !== "ready"} />
      {state !== "ready" && <code className="rt-formula">{tex}</code>}
    </span>
  );
}

/**
 * Small, dependency-free renderer for the markdown subset the model produces in
 * section details (paragraphs, lists, headings, bold, inline code, LaTeX,
 * definition/theorem/example blocks).
 *
 * Everything except KaTeX output is rendered as React text nodes — no
 * `dangerouslySetInnerHTML` — so a model answer can never inject markup.
 */
const INLINE =
  /(\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|\\\((.+?)\\\)|\\\[([\s\S]+?)\\\]|\$\$([\s\S]+?)\$\$|\$([^$\n]+)\$|\*([^*\n]+)\*)/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  INLINE.lastIndex = 0;
  while ((match = INLINE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const [, token, bold, boldAlt, code, formulaInline, formulaBlock, formulaDollarBlock, dollar, italic] = match;
    const key = `${keyPrefix}-${match.index}`;
    if (bold || boldAlt) {
      nodes.push(<strong key={key}>{bold ?? boldAlt}</strong>);
    } else if (code) {
      nodes.push(<code key={key}>{code}</code>);
    } else if (formulaInline || formulaBlock || formulaDollarBlock || dollar) {
      nodes.push(
        <MathFormula
          key={key}
          tex={(formulaInline ?? formulaBlock ?? formulaDollarBlock ?? dollar ?? "").trim()}
          block={Boolean(formulaBlock || formulaDollarBlock)}
        />,
      );
    } else if (italic) {
      nodes.push(<em key={key}>{italic}</em>);
    } else {
      nodes.push(token);
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

type Tone = "definition" | "theorem" | "example" | "warning" | "formula";

interface Block {
  kind: "p" | "h" | "ul" | "ol" | "note";
  lines: string[];
  level?: number;
  label?: string;
  tone?: Tone;
}

const NOTE_PREFIX =
  /^\s*(?:\*\*)?\s*(Определение|Аксиома|Теорема|Лемма|Следствие|Свойство|Пример|Важно|Замечание|Внимание|Формула)\s*(?:\*\*)?\s*[:.—–-]\s*(.+)$/i;

const NOTE_META: Record<string, { label: string; tone: Tone }> = {
  определение: { label: "Определение", tone: "definition" },
  аксиома: { label: "Определение", tone: "definition" },
  теорема: { label: "Теорема", tone: "theorem" },
  лемма: { label: "Теорема", tone: "theorem" },
  следствие: { label: "Теорема", tone: "theorem" },
  свойство: { label: "Свойство", tone: "theorem" },
  пример: { label: "Пример", tone: "example" },
  важно: { label: "Важно", tone: "warning" },
  замечание: { label: "Замечание", tone: "warning" },
  внимание: { label: "Важно", tone: "warning" },
  формула: { label: "Формула", tone: "formula" },
};

function parseBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  // Models and the extractive fallback often put `## Heading` right next to
  // the following paragraph; give every heading its own blank-line chunk.
  const normalized = source
    .replace(/\r\n/g, "\n")
    .replace(/([^\n])\n(#{1,4}\s)/g, "$1\n\n$2")
    .replace(/^(#{1,4}[ \t][^\n]*)$/gm, "$1\n");
  const chunks = normalized.split(/\n{2,}/);
  for (const raw of chunks) {
    const lines = raw.split("\n").map((line) => line.trimEnd()).filter((line, index, all) => line.trim() || (index > 0 && index < all.length - 1));
    const trimmed = lines.filter((line) => line.trim());
    if (trimmed.length === 0) continue;

    const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed[0]);
    if (heading && trimmed.length === 1) {
      blocks.push({ kind: "h", lines: [heading[2]], level: heading[1].length });
      continue;
    }

    const note = NOTE_PREFIX.exec(trimmed[0]);
    if (note) {
      const meta = NOTE_META[note[1].toLowerCase()];
      const body = [note[2], ...trimmed.slice(1)].filter((line) => line.trim());
      if (meta && body.length > 0) {
        blocks.push({ kind: "note", lines: body, label: meta.label, tone: meta.tone });
        continue;
      }
    }

    if (trimmed.every((line) => /^[-*•]\s+/.test(line))) {
      blocks.push({ kind: "ul", lines: trimmed.map((line) => line.replace(/^[-*•]\s+/, "")) });
      continue;
    }
    if (trimmed.every((line) => /^\d+[.)]\s+/.test(line))) {
      blocks.push({ kind: "ol", lines: trimmed.map((line) => line.replace(/^\d+[.)]\s+/, "")) });
      continue;
    }
    blocks.push({ kind: "p", lines: trimmed });
  }
  return blocks;
}

function renderLines(lines: string[], key: string): ReactNode[] {
  return lines.map((line, lineIndex) => (
    <Fragment key={`${key}-${lineIndex}`}>
      {lineIndex > 0 && <br />}
      {renderInline(line, `${key}-${lineIndex}`)}
    </Fragment>
  ));
}

/** Inline subset for headings and short labels: bold, code and formulas. */
export function InlineText({ text }: { text: string }) {
  return <>{renderInline(text, "inline")}</>;
}

export function RichText({ text, className }: Props) {
  if (!text?.trim()) return null;
  const blocks = parseBlocks(text);

  return (
    <div className={`rich-text ${className ?? ""}`.trim()}>
      {blocks.map((block, index) => {
        const key = `block-${index}`;
        if (block.kind === "h") {
          const content = renderInline(block.lines[0], key);
          return block.level && block.level <= 2 ? (
            <h4 key={key}>{content}</h4>
          ) : (
            <h5 key={key}>{content}</h5>
          );
        }
        if (block.kind === "note") {
          return (
            <aside key={key} className={`rt-note rt-note--${block.tone ?? "definition"}`}>
              <span className="rt-note__label">{block.label}</span>
              <div className="rt-note__body">{renderLines(block.lines, key)}</div>
            </aside>
          );
        }
        if (block.kind === "ul" || block.kind === "ol") {
          const List = block.kind === "ul" ? "ul" : "ol";
          return (
            <List key={key}>
              {block.lines.map((line, lineIndex) => (
                <li key={`${key}-${lineIndex}`}>{renderInline(line, `${key}-${lineIndex}`)}</li>
              ))}
            </List>
          );
        }
        return <p key={key}>{renderLines(block.lines, key)}</p>;
      })}
    </div>
  );
}
