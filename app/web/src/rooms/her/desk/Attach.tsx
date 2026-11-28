// The Pocket's attach button: opens the phone's file or photo picker (its camera among them, where it offers one), and says
// where a drop got to.
import { useRef } from 'preact/hooks';
import { dropped } from './dropOnBench';
import { ACCEPT } from './drops';

export function Attach({ disabled, onFiles }: { disabled: boolean; onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const { working, bench, said } = dropped.value;
  return (
    <div class="pocket-attach">
      <button class="btn" type="button" disabled={disabled || working} onClick={() => input.current?.click()}>
        {working ? 'Putting it on a bench…' : 'Attach a photo or file'}
      </button>
      <input ref={input} class="sr-only" type="file" multiple accept={ACCEPT} tabIndex={-1} aria-label="Photo or file to attach"
        onChange={(e) => {
          const got = Array.from(e.currentTarget.files ?? []);
          e.currentTarget.value = '';
          if (got.length) onFiles(got);
        }} />
      {said && <p class="compose-note over" role="status">{said}{bench !== null && <> <a href={`/workshop/${bench}`}>Open the bench</a></>}</p>}
    </div>
  );
}
