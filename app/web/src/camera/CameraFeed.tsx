// A camera's live feed as a card over the screen (`card.ts`): it slides in, plays muted, says "The camera did not answer"
// when the connection fails, and goes by a swipe, its close button, or on its own when its time is up. The card is never
// blank: until the picture plays it says it is connecting.
import { useEffect, useRef, useState } from 'preact/hooks';
import type { Card } from './card';
import { swiped } from './swipe';

export function CameraFeed({ card }: { card: Card }) {
  const shown = card.showing.value;
  const video = useRef<HTMLVideoElement>(null);
  const from = useRef<number | null>(null);
  const [drag, setDrag] = useState(0);
  const title = shown?.feed.camera_title;
  // one connection per feed shown: a phase change is not a new feed
  useEffect(() => (title && video.current ? card.open(video.current).close : undefined), [title]);
  if (!shown) return null;
  const release = (): void => {
    from.current = null;
    if (swiped(drag)) card.dismiss();
    setDrag(0);
  };
  return (
    <aside class="cam-feed" role="region" aria-label={`Live camera: ${shown.feed.camera_title}`}
      style={drag ? { transform: `translateX(${drag}px)`, opacity: 1 - Math.min(Math.abs(drag) / 300, 0.6) } : undefined}
      onPointerDown={(e) => { from.current = e.clientX; }}
      onPointerMove={(e) => { if (from.current !== null) setDrag(e.clientX - from.current); }}
      onPointerUp={release} onPointerCancel={release}>
      <header class="cam-head">
        <span class="cam-title">{shown.feed.camera_title}</span>
        <button class="btn sm ghost" type="button" aria-label="Dismiss the camera" onClick={card.dismiss}>✕</button>
      </header>
      <div class="cam-view" data-phase={shown.phase}>
        <video ref={video} muted playsInline autoPlay onPlaying={card.playing} />
        {shown.phase === 'connecting' && <p class="cam-note">Connecting to the camera…</p>}
        {shown.phase === 'failed' && <p class="cam-note cam-failed">The camera did not answer.</p>}
      </div>
    </aside>
  );
}
