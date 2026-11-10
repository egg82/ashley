// How a piece's body is shown, chosen by its kind's data (`GET /api/workshop/kinds`), never by its name: a `stored`
// kind's body is its content, shown by the kind's `format` (Markdown, plain text as typed, code in a block, or an
// automation's summary with its JSON, or a reader's page text with her highlight, `ReaderView.tsx`, or a diagram's Mermaid source drawn, `DiagramView.tsx`, or a recipe as a card, `RecipeView.tsx`); a `live` kind's body is a reference shown in a frame (`FrameView.tsx`); a `large` kind's body names bytes the server keeps, shown by `FileView.tsx`; a
// kind the rules no longer list is shown as plain text, saying so. The glyph is the kind's label's first letter.
import type { ComponentChildren } from 'preact';
import { useLayoutEffect, useRef, useState } from 'preact/hooks';
import type { BenchPiece, PieceKind } from '../../../api/types';
import { CodeBlock } from '../../../highlight/CodeBlock';
import { languageNamed } from '../../../highlight/languages';
import { MarkdownText } from '../../her/Markdown';
import { AutomationView } from './AutomationView';
import { DiagramView } from './DiagramView';
import { JobView } from './JobView';
import { MeasurementsView } from './MeasurementsView';
import { ModelView } from './ModelView';
import { WakeView } from './WakeView';
import { SiteView, VideoView } from './FrameView';
import { FileView } from './FileView';
import { MediaView } from './MediaView';
import { ReaderView } from './ReaderView';
import { RecipeView } from './RecipeView';
import { isModel } from './modelFacts';

/** The tile glyph for a kind: its label's first letter, or "?" for a kind the rules don't list. */
export function glyphOf(kind: PieceKind | undefined): string {
  return kind ? kind.label.slice(0, 1).toUpperCase() : '?';
}

/** The tallest a body shows before it is cut with a fade and a "Show all". */
const CLAMP_PX = 360;

/** A body cut at its card's bottom edge (at least `CLAMP_PX`) when it is taller, with a fade and "Show all", which grows
 * the card to all of it. The fade and the button show only while the body overflows what the card shows. */
function Clamp({ text, children }: { text: string; children: ComponentChildren }) {
  const box = useRef<HTMLDivElement>(null);
  const [tall, setTall] = useState(false);
  const [over, setOver] = useState(false);
  const [open, setOpen] = useState(false);
  useLayoutEffect(() => {
    const el = box.current;
    const body = el?.firstElementChild as HTMLElement | null;
    if (!el || !body) return;
    const measure = () => {
      setTall(body.scrollHeight > CLAMP_PX + 24);
      if (!open) setOver(body.scrollHeight > body.clientHeight + 1);
    };
    measure();
    const watch = new ResizeObserver(measure);
    watch.observe(el);
    watch.observe(body);
    return () => watch.disconnect();
  }, [text, open, tall]);
  const cls = `clamp${tall && !open ? ' cut' : ''}${over ? ' over' : ''}${open ? ' open' : ''}`;
  return (
    <div class={cls} ref={box} style={{ '--clamp': `${CLAMP_PX}px` }}>
      {children}
      {tall && (over || open) && (
        <button class="btn sm clamp-more" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? 'Show less' : 'Show all'}
        </button>
      )}
    </div>
  );
}

function Unknown({ piece }: { piece: BenchPiece }) {
  return (
    <Clamp text={piece.body}>
      <div class="pbody plain">
        <span class="unk">a kind this page doesn't know, “{piece.kind}”, shown as plain text</span>
        <p>{piece.body}</p>
      </div>
    </Clamp>
  );
}

function Live({ bench, piece, format }: { bench: number; piece: BenchPiece; format: PieceKind['format'] }) {
  if (!piece.body.trim()) return <div class="pbody"><span class="meta">Empty. Edit to set it.</span></div>;
  if (format === 'site') return <SiteView piece={piece} />;
  if (format === 'video') return <VideoView bench={bench} piece={piece} />;
  return <div class="pbody"><span class="unk">a live source, which this page can't show</span></div>;
}

function Written({ piece, kind }: { piece: BenchPiece; kind: PieceKind }) {
  const { format } = kind;
  if (format === 'plain') return <div class="pbody plain"><p>{piece.body}</p></div>;
  if (format === 'code') return <div class="pbody code"><CodeBlock code={piece.body} language={languageNamed(kind.language)} /></div>;
  if (format === 'automation') return <AutomationView body={piece.body} />;
  if (format === 'wake') return <WakeView body={piece.body} />;
  if (format === 'measurements') return <MeasurementsView body={piece.body} />;
  if (format === 'recipe') return <RecipeView piece={piece} />;
  if (format === 'diagram') return <DiagramView body={piece.body} />;
  return <div class="pbody md"><MarkdownText text={piece.body} /></div>;
}

function Stored({ piece, kind }: { piece: BenchPiece; kind: PieceKind }) {
  if (isModel(kind)) return <ModelView piece={piece} kind={kind} />;
  if (!piece.body.trim()) return <div class="pbody"><span class="meta">Empty. Edit to write in it.</span></div>;
  if (kind.format === 'diagram') return <Written piece={piece} kind={kind} />;
  return <Clamp text={piece.body}><Written piece={piece} kind={kind} /></Clamp>;
}

export function PieceBody({ bench, piece, kind, closed = false }: { bench: number; piece: BenchPiece; kind: PieceKind | undefined; closed?: boolean }) {
  if (!kind) return <Unknown piece={piece} />;
  if (kind.format === 'job') return <JobView bench={bench} body={piece.body} closed={closed} />;
  if (kind.format === 'reader') return <ReaderView bench={bench} piece={piece} closed={closed} />;
  if (kind.format === 'clip' || kind.format === 'audio') return <MediaView bench={bench} piece={piece} video={kind.format === 'clip'} />;
  if (kind.family === 'large') return <FileView piece={piece} />;
  return kind.family === 'live' ? <Live bench={bench} piece={piece} format={kind.format} /> : <Stored piece={piece} kind={kind} />;
}
