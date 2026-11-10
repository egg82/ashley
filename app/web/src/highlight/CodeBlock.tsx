// Source code in a `<pre>`: plain at once, then coloured when the highlighter has loaded. `language` is a fence tag or
// a kind's `language`; null lets the highlighter judge the text. The highlighter is imported here, on first render, so
// it is a chunk of its own and the first paint never carries it.
import { useEffect, useState } from 'preact/hooks';

export function CodeBlock({ code, language, class: cls }: { code: string; language: string | null; class?: string }) {
  const [html, setHtml] = useState<{ code: string; language: string | null; html: string } | null>(null);
  useEffect(() => {
    let live = true;
    import('./highlight.ts')
      .then((m) => m.highlightCode(code, language))
      .then((h) => { if (live && h !== null) setHtml({ code, language, html: h }); })
      .catch((e: unknown) => console.warn('highlight failed', e instanceof Error ? e.message : e));
    return () => { live = false; };
  }, [code, language]);
  const done = html !== null && html.code === code && html.language === language ? html.html : null;
  return (
    <pre class={cls}>
      {done === null ? <code>{code}</code> : <code class="hljs" dangerouslySetInnerHTML={{ __html: done }} />}
    </pre>
  );
}
