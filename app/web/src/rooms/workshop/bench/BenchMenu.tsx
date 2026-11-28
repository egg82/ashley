// The bench's ⋯ menu, for what is set once rather than used while working: how she works on this bench (its kind of work
// and method, `Method.tsx`), uploading files from a picker (dropping them on the canvas is the usual way, `Upload.tsx`),
// and closing the bench.
import { useLocation } from 'preact-iso';
import { useEffect, useRef, useState } from 'preact/hooks';
import type { BenchDetail, WorkshopKinds } from '../../../api/types';
import { close } from '../model/benches';
import { Method } from './Method';
import { UploadPick } from './Upload';

function Close({ id }: { id: number }) {
  const [asking, setAsking] = useState(false);
  const [failed, setFailed] = useState(false);
  const { route } = useLocation();
  if (!asking) return <button class="btn sm ghost" type="button" onClick={() => setAsking(true)}>Close the bench</button>;
  const confirm = async () => {
    if (await close(id)) route('/workshop');
    else setFailed(true);
  };
  return (
    <span class="ws-ask" role="group" aria-label="Close this bench">
      <span class="meta">{failed ? "Didn't close. Try again." : "It's kept, but leaves your benches."}</span>
      <button class="btn sm" type="button" onClick={() => void confirm()}>Close it</button>
      <button class="btn sm ghost" type="button" onClick={() => setAsking(false)}>Keep it open</button>
    </span>
  );
}

function useDismiss(menu: { current: HTMLDetailsElement | null }): void {
  useEffect(() => {
    const away = (e: Event) => {
      const el = menu.current;
      if (el?.open && !(e.target instanceof Node && el.contains(e.target))) el.open = false;
    };
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && menu.current && (menu.current.open = false);
    document.addEventListener('pointerdown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('pointerdown', away);
      document.removeEventListener('keydown', esc);
    };
  }, []);
}

export function BenchMenu({ bench, rules, full }: { bench: BenchDetail; rules: WorkshopKinds | null; full: boolean }) {
  const menu = useRef<HTMLDetailsElement>(null);
  useDismiss(menu);
  const closed = bench.bench.closed_at !== null;
  return (
    <details class="bb-menu" ref={menu}>
      <summary class="btn sm ghost bb-more" aria-label="More for this bench" title="More for this bench">⋯</summary>
      <div class="bb-pop">
        <span class="label">How she works on this</span>
        <Method bench={bench} rules={rules} />
        {!closed && (
          <div class="bb-row">
            <UploadPick bench={bench.bench.id} disabled={!rules || full} />
            <Close id={bench.bench.id} />
          </div>
        )}
      </div>
    </details>
  );
}
