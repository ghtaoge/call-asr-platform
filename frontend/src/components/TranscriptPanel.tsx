import type { Segment } from "../types";

interface Props {
  segments: Segment[];
}

export function TranscriptPanel({ segments }: Props) {
  return (
    <section className="transcript" aria-label="通话内容">
      <h2>通话内容</h2>
      {segments.length === 0 ? (
        <p className="empty">上传录音或开始实时演示后，分段转写会显示在这里。</p>
      ) : (
        <div className="segmentList">
          {segments.map((segment) => (
            <article className={`segment ${segment.speaker}`} key={segment.id}>
              <div className="segmentMeta">
                <strong>{speakerName(segment.speaker)}</strong>
                <span>
                  {Math.round(segment.start_ms / 1000)}s - {Math.round(segment.end_ms / 1000)}s
                </span>
                <span>{segment.emotion.label}</span>
              </div>
              <p>{renderHighlightedText(segment)}</p>
              <small>{segment.translation}</small>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function speakerName(speaker: Segment["speaker"]) {
  return speaker === "sales" ? "销售" : speaker === "customer" ? "客户" : "未知";
}

function renderHighlightedText(segment: Segment) {
  if (segment.sensitive_hits.length === 0) return segment.text;
  const ordered = [...segment.sensitive_hits].sort((a, b) => a.start - b.start);
  const parts: JSX.Element[] = [];
  let cursor = 0;
  for (const hit of ordered) {
    if (cursor < hit.start) {
      parts.push(<span key={`${hit.word}-${cursor}`}>{segment.text.slice(cursor, hit.start)}</span>);
    }
    parts.push(
      <mark className={`hit-${hit.level}`} key={`${hit.word}-${hit.start}`}>
        {segment.text.slice(hit.start, hit.end)}
      </mark>
    );
    cursor = hit.end;
  }
  if (cursor < segment.text.length) {
    parts.push(<span key="tail">{segment.text.slice(cursor)}</span>);
  }
  return parts;
}
