// The picture of a model: its GLB drawn by three.js, imported on first use so no other page carries it. In a look
// (`AsSheet`) it is the four-view sheet, or one side of it when the look names one (`LookSide`), drawn once; otherwise a view to orbit. A browser that cannot draw WebGL, or a
// file that will not load, says so in the picture's place.
import { useContext, useEffect, useRef, useState } from 'preact/hooks';
import { VIEWS, extentText, type Vec3, type ViewPreset } from '../solid/views';
import { tracked } from '../solid/drawing';
import { NoWebGl } from '../solid/noWebGl';
import { AsSheet, LookSide } from '../solid/sheet';

type Phase = { is: 'loading' } | { is: 'drawn'; size: Vec3 } | { is: 'no_webgl' } | { is: 'failed' };

const SAYS = {
  no_webgl: "This browser can't draw 3D. The downloads and the checks are below.",
  failed: "The model couldn't be loaded. The downloads and the checks are below.",
};

function nextFrame(): Promise<void> {
  return new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => done())));
}

async function show(canvas: HTMLCanvasElement, url: string, sheet: boolean, side: ViewPreset | null): Promise<{ size: Vec3; dispose(): void }> {
  const [stage, res] = await Promise.all([import('../solid/stage'), fetch(url)]);
  if (!res.ok) throw new Error(`model fetch ${res.status}`);
  const glb = await res.arrayBuffer();
  const drawn = await (sheet ? stage.drawSheet(canvas, glb, side) : stage.openStage(canvas, glb));
  await nextFrame();
  return drawn;
}

export function ModelCanvas({ url, runId, title }: { url: string; runId: number; title: string }) {
  const sheet = useContext(AsSheet);
  const side = useContext(LookSide);
  const canvas = useRef<HTMLCanvasElement>(null);
  const latest = useRef(url);
  latest.current = url;
  const [phase, setPhase] = useState<Phase>({ is: 'loading' });
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    let live = true;
    let dispose: (() => void) | null = null;
    setPhase({ is: 'loading' });
    void tracked(show(el, latest.current, sheet, side).then(
      (d) => { if (live) { dispose = d.dispose; setPhase({ is: 'drawn', size: d.size }); } else d.dispose(); },
      (e: unknown) => {
        console.warn('model view failed', e instanceof Error ? e.message : e);
        if (live) setPhase({ is: e instanceof NoWebGl ? 'no_webgl' : 'failed' });
      },
    ));
    return () => { live = false; dispose?.(); };
  }, [runId, sheet, side]);
  const broken = phase.is === 'no_webgl' || phase.is === 'failed';
  return (
    <div class={`mview${sheet ? ' sheet' : ''}`} data-phase={phase.is}>
      {broken && <p class="mview-says meta" role="status">{SAYS[phase.is]}</p>}
      <canvas key={runId} ref={canvas} role="img" aria-label={sheet ? (side ? `${side.label} view of ${title}` : `Four views of ${title}`) : `3D view of ${title}`} hidden={broken} />
      {sheet && !side && !broken && (
        <div class="mview-grid" aria-hidden="true">
          {VIEWS.map((v) => <span key={v.id}>{v.label}</span>)}
        </div>
      )}
      {phase.is === 'drawn' && <p class="mview-size meta">{extentText(phase.size)}{sheet ? null : <span class="mview-hint"> · drag to turn, scroll to zoom</span>}</p>}
    </div>
  );
}
