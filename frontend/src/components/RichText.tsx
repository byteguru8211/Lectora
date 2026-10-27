import { Fragment, type ReactNode } from "react";

interface Props {
  text: string;
  className?: string;
}

/**
 * Small, dependency-free renderer for the markdown subset the model produces in
 * section details (paragraphs, lists, headings, bold, inline code, LaTeX).
 *
 * Everything is rendered as React text nodes — no `dangerouslySetInnerHTML` —
 * so a model answer can never inject markup into the page.
 */
const INLINE = /(\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|\\\((.+?)\\\)|\\\[([\s\S]+?)\\\]|\$([^$]+)\$|\*([^*\n]+)\*)/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  INLINE.lastIndex = 0;
  while ((match = INLINE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const [, token, bold, boldAlt, code, formulaInline, formulaBlock, dollar, italic] = match;
    const key = `${keyPrefix}-${match.index}`;
    if (bold || boldAlt) {
      nodes.push(<strong key={key}>{bold ?? boldAlt}</strong>);
    } else if (code) {
      nodes.push(<code key={key}>{code}</code>);
    } else if (formulaInline || formulaBlock || dollar) {
      nodes.push(
        <code key={key} className="rt-formula">
          {(formulaInline ?? formulaBlock ?? dollar ?? "").trim()}
        </code>,
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

interface Block {
  kind: "p" | "h" | "ul" | "ol";
  lines: string[];
  level?: number;
}

function parseBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  const chunks = source.replace(/\r\n/g, "\n").split(/\n{2,}/);
  for (const raw of chunks) {
    const lines = raw.split("\n").map((line) => line.trimEnd()).filter((line, index, all) => line.trim() || (index > 0 && index < all.length - 1));
    const trimmed = lines.filter((line) => line.trim());
    if (trimmed.length === 0) continue;

    const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed[0]);
    if (heading && trimmed.length === 1) {
      blocks.push({ kind: "h", lines: [heading[2]], level: heading[1].length });
      continue;
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
        return (
          <p key={key}>
            {block.lines.map((line, lineIndex) => (
              <Fragment key={`${key}-${lineIndex}`}>
                {lineIndex > 0 && <br />}
                {renderInline(line, `${key}-${lineIndex}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
