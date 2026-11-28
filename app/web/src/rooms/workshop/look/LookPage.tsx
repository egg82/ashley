// The page a browser pod photographs for `bench_look` (`/look/<token>`), outside the person shell: the bench, or one
// piece of it, drawn as the bench screen draws a closed bench (`LookCanvas.tsx`), with the kinds the same token carries.
// It marks the body `data-look="ready"` once every card is laid out, their images have loaded and every model's
// four-view sheet has drawn its frame, which the pod waits for; a link that does not work says so and is never marked.
import { useEffect, useState } from 'preact/hooks';
import { getLook } from '../../../api/client';
import type { LookPage as Page } from '../../../api/types';
import { allDrawn } from '../solid/drawing';
import { AsSheet, LookSide } from '../solid/sheet';
import { sideNamed } from '../solid/views';
import { LookCanvas } from './LookCanvas';

const frame = () => new Promise<void>((r) => requestAnimationFrame(() => r()));

/** Resolves once no card waits to be measured and the layout has stood still for two frames. */
async function laidOut(root: HTMLElement): Promise<void> {
  do await frame(); while (root.querySelector('.bc-card.measuring'));
  await frame();
  await frame();
}

async function drawn(root: HTMLElement): Promise<void> {
  await document.fonts.ready;
  await Promise.all(Array.from(root.querySelectorAll('img')).map((i) => i.decode().catch(() => undefined)));
  await allDrawn();
  await laidOut(root);
}

export function LookPage({ token }: { token: string }) {
  const [page, setPage] = useState<Page | 'gone' | null>(null);
  useEffect(() => {
    getLook(token).then(setPage, () => setPage('gone'));
  }, [token]);
  useEffect(() => {
    const root = document.getElementById('app');
    if (!page || page === 'gone' || !root) return;
    void drawn(root).then(() => { document.body.dataset.look = 'ready'; });
  }, [page]);
  if (page === null) return <p class="chat-quiet meta">Reading…</p>;
  if (page === 'gone') return <p class="chat-quiet meta">This link no longer works.</p>;
  const bench = { ...page.view, bench: { ...page.view.bench, closed_at: page.view.bench.closed_at ?? new Date().toISOString() } };
  return (
    <AsSheet.Provider value={true}>
      <LookSide.Provider value={sideNamed(new URLSearchParams(location.search).get('view'))}>
        <div class="look-page">
          <LookCanvas bench={bench} rules={page.rules} />
        </div>
      </LookSide.Provider>
    </AsSheet.Provider>
  );
}
