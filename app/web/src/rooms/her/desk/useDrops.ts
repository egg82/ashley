// The Pocket's drop and paste handling: classifies what arrived (`drops.ts`) and sends it where it goes.
import { useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { pastedOn } from '../attached';
import { classifyDrop, textOf } from './drops';
import { dropOnBench } from './dropOnBench';

type Send = (text: string, pasted: string | null) => Promise<string | null>;

const carriesFiles = (e: DragEvent) => e.dataTransfer?.types.includes('Files') ?? false;
const carriesText = (e: DragEvent) => e.dataTransfer?.types.some((t) => t === 'text/plain' || t === 'text/uri-list') ?? false;

/** Handlers for the Pocket's root, and `files` to call with chosen files, for `thread` and its `send`. */
export function useDrops(thread: string, send: Send) {
  const { route } = useLocation();
  const [over, setOver] = useState(0);
  const files = async (got: readonly File[]) => {
    const bench = await dropOnBench(thread, got);
    if (bench !== null) route(`/workshop/${bench}`);
  };
  const arrive = (text: string, got: readonly File[]) => {
    const kind = classifyDrop(text, got.length);
    if (kind === 'files') void files(got);
    else if (kind === 'chip') pastedOn(thread, text);
    else if (kind === 'line') void send(text.trim(), null);
  };
  const taking = (e: DragEvent) => carriesFiles(e) || carriesText(e);
  return {
    over: over > 0,
    files,
    handlers: {
      onDragEnter: (e: DragEvent) => taking(e) && (e.preventDefault(), setOver((n) => n + 1)),
      onDragOver: (e: DragEvent) => taking(e) && e.preventDefault(),
      onDragLeave: (e: DragEvent) => taking(e) && setOver((n) => Math.max(0, n - 1)),
      onDrop: (e: DragEvent) => {
        if (!taking(e) || !e.dataTransfer) return;
        e.preventDefault();
        setOver(0);
        arrive(textOf(e.dataTransfer), Array.from(e.dataTransfer.files));
      },
      onPaste: (e: ClipboardEvent) => {
        const got = Array.from(e.clipboardData?.files ?? []);
        if (got.length === 0) return;
        e.preventDefault();
        arrive('', got);
      },
    },
  };
}
