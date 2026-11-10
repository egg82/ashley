// Adding files to a bench: a button that opens the file picker, and dropping files anywhere on the pieces column.
// Only files count as a drop (`dragging`); a piece being dragged by its grip is the page's own pointer drag.
import { useRef, useState } from 'preact/hooks';
import type { ComponentChildren } from 'preact';
import { uploadAll, uploading } from '../model/upload';

export function UploadButton({ bench, disabled }: { bench: number; disabled: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <button class="btn sm" type="button" disabled={disabled} onClick={() => input.current?.click()}>
        {uploading.value ? `Uploading ${uploading.value}…` : 'Upload'}
      </button>
      <input ref={input} class="sr-only" type="file" multiple tabIndex={-1} aria-label="Files to upload"
        onChange={(e) => {
          const files = Array.from(e.currentTarget.files ?? []);
          e.currentTarget.value = '';
          if (files.length) void uploadAll(bench, files);
        }} />
    </>
  );
}

const hasFiles = (e: DragEvent) => e.dataTransfer?.types.includes('Files') ?? false;

/** The column that takes dropped files for `bench`; it shows a drop target while files are over it. */
export function DropFiles({ bench, enabled, children }: { bench: number; enabled: boolean; children: ComponentChildren }) {
  const [over, setOver] = useState(0);
  const taking = (e: DragEvent) => enabled && hasFiles(e);
  return (
    <section class={`col pieces${over ? ' dropping' : ''}`} aria-label="Pieces"
      onDragEnter={(e) => taking(e) && (e.preventDefault(), setOver((n) => n + 1))}
      onDragOver={(e) => taking(e) && e.preventDefault()}
      onDragLeave={(e) => taking(e) && setOver((n) => Math.max(0, n - 1))}
      onDrop={(e) => {
        if (!taking(e)) return;
        e.preventDefault();
        setOver(0);
        const files = Array.from(e.dataTransfer?.files ?? []);
        if (files.length) void uploadAll(bench, files);
      }}>
      {children}
      {over > 0 && <div class="drop-hint" aria-hidden="true">Drop to add to the bench</div>}
    </section>
  );
}
