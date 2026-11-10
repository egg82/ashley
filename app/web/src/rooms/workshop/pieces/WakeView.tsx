// A wake rule piece read as what it does: the event from the house it answers, her brief for that turn and the tools it
// may use, with the JSON folded under it, in the automation view's classes. A body that is not an object is shown as
// the text it is. Edited as JSON in the ordinary editor.
type Rule = { event?: unknown; brief?: unknown; tools?: unknown };

function parsed(body: string): Rule | null {
  try {
    const got: unknown = JSON.parse(body);
    return got && typeof got === 'object' && !Array.isArray(got) ? (got as Rule) : null;
  } catch {
    return null;
  }
}

export function WakeView({ body }: { body: string }) {
  const rule = parsed(body);
  if (!rule) return <div class="pbody plain"><p>{body}</p></div>;
  const tools = Array.isArray(rule.tools) ? rule.tools.filter((t): t is string => typeof t === 'string') : [];
  return (
    <div class="pbody auto">
      <p class="auto-name">{typeof rule.event === 'string' ? <>When the house sends <b>{rule.event}</b></> : <span class="meta">No event yet</span>}</p>
      {typeof rule.brief === 'string' && <p class="auto-desc">{rule.brief}</p>}
      <div class="auto-sec">
        <span class="meta">May use</span>
        {tools.length ? <ul>{tools.map((t) => <li key={t}><b>{t}</b></li>)}</ul> : <p class="meta">No tools</p>}
      </div>
      <details class="auto-json"><summary class="meta">JSON</summary><pre><code>{JSON.stringify(rule, null, 2)}</code></pre></details>
    </div>
  );
}
