// A reader piece: a web page's text as she read it, one paragraph to a line, with the original linked. Her highlight
// (`piece.pointer`) is drawn on its passage and brought into view inside the text's own scroll box, smoothly unless
// motion is reduced, once for each new highlight and once when the piece first shows after a reload.
// A transcript (`page.recording`) has each line as a button that plays its recording from that line's start, by the
// same cue she gives (`cueBenchPlayer`); while the recording plays, the line being spoken is marked and kept in view.
import { useEffect, useRef } from 'preact/hooks';
import type { BenchPiece } from '../../../api/types';
import { cueBenchPlayer } from '../../../session/live';
import { reduced } from '../../../shell/motion';
import { apply } from '../model/bench';
import { cut } from '../model/passage';
import { usePlayhead } from '../model/playhead';
import { lineAt } from '../model/transcript';

type Pointer = NonNullable<BenchPiece['pointer']>;

/** The address as an https URL, or null: the server checks it, but a page does not trust what it links. */
function httpsUrl(text: string): URL | null {
  try {
    const url = new URL(text);
    return url.protocol === 'https:' ? url : null;
  } catch {
    return null;
  }
}

function Marked({ text, point, mark }: { text: string; point: Pointer; mark: { current: HTMLElement | null } }) {
  const { before, hit, after } = cut(text, point.start, point.end);
  return (
    <>
      {before}
      <mark class="reader-mark" ref={mark}>{hit}</mark>
      {after}
    </>
  );
}

type Recording = NonNullable<NonNullable<BenchPiece['reader']>['recording']>;

/** Plays the recording from `seconds`: a seek, then a play. */
function playFrom(bench: number, recording: Recording, seconds: number): void {
  cueBenchPlayer(bench, recording.piece_id, { action: 'seek', seconds });
  cueBenchPlayer(bench, recording.piece_id, { action: 'play', seconds: null });
}

function Line({ text, point, mark, spoken, onPlay }: {
  text: string; point: Pointer | null; mark: { current: HTMLElement | null }; spoken: boolean; onPlay: (() => void) | null;
}) {
  const inside = point ? <Marked text={text} point={point} mark={mark} /> : text;
  if (!onPlay) return <p>{inside}</p>;
  return (
    <p>
      <button class={spoken ? 'reader-line spoken' : 'reader-line'} type="button" aria-current={spoken ? 'true' : undefined} onClick={onPlay}>
        {inside}
      </button>
    </p>
  );
}

function bringIntoView(box: HTMLElement, mark: HTMLElement): void {
  const top = mark.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
  box.scrollTo({ top: Math.max(0, top - (box.clientHeight - mark.offsetHeight) / 2), behavior: reduced() ? 'auto' : 'smooth' });
}

export function ReaderView({ bench, piece, closed }: { bench: number; piece: BenchPiece; closed: boolean }) {
  const page = piece.reader;
  const point = piece.pointer;
  const recording = page?.recording ?? null;
  const box = useRef<HTMLDivElement>(null);
  const mark = useRef<HTMLElement | null>(null);
  const shown = useRef<number | null>(null);
  const head = usePlayhead(bench, recording?.piece_id ?? null);
  const spoken = recording && head?.playing ? lineAt(recording.starts, head.seconds) : -1;
  useEffect(() => {
    if (spoken < 0) return;
    const line = box.current?.querySelector<HTMLElement>('.reader-line.spoken');
    if (box.current && line) bringIntoView(box.current, line);
  }, [spoken]);
  useEffect(() => {
    if (!point || shown.current === point.seq) return;
    shown.current = point.seq;
    const frame = requestAnimationFrame(() => box.current && mark.current && bringIntoView(box.current, mark.current));
    return () => cancelAnimationFrame(frame);
  }, [point?.seq]);
  if (!page) return <div class="pbody"><span class="meta">Empty. Ashley puts a page here.</span></div>;
  const url = httpsUrl(page.url);
  return (
    <div class="pbody reader">
      <div class="reader-text" ref={box} tabIndex={0} role="region" aria-label={`Text of ${page.title || piece.title}`}>
        {page.paragraphs.map((text, i) => (
          <Line key={i} text={text} point={point && point.paragraph === i ? point : null} mark={mark} spoken={i === spoken}
            onPlay={recording ? () => playFrom(bench, recording, recording.starts[i] ?? 0) : null} />
        ))}
      </div>
      <div class="frame-foot">
        <span class="meta frame-host">{url ? url.hostname : page.url ? 'address not shown' : 'no web page'}{page.title && ` · ${page.title}`}</span>
        {point && !closed && (
          <button class="btn sm ghost" type="button"
            onClick={() => void apply({ type: 'clear_point', piece_id: piece.id, base_version: piece.piece_version })}>
            Clear highlight
          </button>
        )}
        {url && <a class="btn sm ghost" href={url.href} target="_blank" rel="noopener noreferrer">Open the original</a>}
      </div>
    </div>
  );
}
