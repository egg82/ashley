// A diagram piece: its body is Mermaid source, drawn as an SVG in the house colours. A body Mermaid cannot read shows
// its message and the source beneath, never an empty box. The drawing registers with `tracked`, so a look waits for it.
import { useEffect, useState } from 'preact/hooks';
import { draw, loadMermaid, themeVariables, type Drawn } from '../diagram/draw';
import { tracked } from '../solid/drawing';

function tokens(): (token: string) => string {
  const style = getComputedStyle(document.documentElement);
  return (token) => style.getPropertyValue(token);
}

export function DiagramView({ body }: { body: string }) {
  const [shown, setShown] = useState<{ body: string; drawn: Drawn } | null>(null);
  useEffect(() => {
    let live = true;
    void tracked(loadMermaid().then((m) => draw(m, body, themeVariables(tokens()))).then(
      (drawn) => { if (live) setShown({ body, drawn }); },
      (e: unknown) => {
        console.warn('diagram failed to load', e instanceof Error ? e.message : e);
        if (live) setShown({ body, drawn: { is: 'error', message: 'The diagram drawing code could not be loaded.' } });
      },
    ));
    return () => { live = false; };
  }, [body]);
  const drawn = shown?.body === body ? shown.drawn : null;
  if (drawn?.is === 'error') {
    return (
      <div class="pbody diagram" data-phase="error">
        <p class="diagram-error" role="alert">{drawn.message}</p>
        <pre class="diagram-source"><code>{body}</code></pre>
      </div>
    );
  }
  if (drawn === null) return <div class="pbody diagram" data-phase="loading"><span class="meta">Drawing…</span></div>;
  return <div class="pbody diagram" data-phase="drawn" role="img" aria-label="Diagram" dangerouslySetInnerHTML={{ __html: drawn.svg }} />;
}
