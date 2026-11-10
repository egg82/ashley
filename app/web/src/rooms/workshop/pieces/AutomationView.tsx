// An automation piece's body read as Home Assistant's own config: its name and description, then When (triggers), Only
// if (conditions) and Then (actions), one line each, and the JSON itself folded under it. A body that is not an object
// is shown as the text it is. Edited as JSON in the ordinary editor.
type Item = Record<string, unknown>;
type Config = { alias?: unknown; description?: unknown; mode?: unknown; triggers?: unknown; conditions?: unknown; actions?: unknown };

const HEADS = ['trigger', 'platform', 'condition', 'action', 'service'];
const SHOWN = ['to', 'from', 'state', 'at', 'event', 'after', 'before', 'weekday', 'for', 'above', 'below', 'zone', 'value_template'];

function short(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(short).join(', ');
  if (value && typeof value === 'object') return Object.entries(value).map(([k, v]) => `${short(v)} ${k}`).join(' ');
  return String(value);
}

function line(item: Item): { head: string; rest: string } {
  const key = HEADS.find((k) => typeof item[k] === 'string');
  const head = key ? String(item[key]) : Object.keys(item)[0] ?? '—';
  const entity = item.entity_id ?? (item.target as Item | undefined)?.entity_id;
  const parts = SHOWN.filter((k) => item[k] !== undefined).map((k) => `${k.replace('_', ' ')} ${short(item[k])}`);
  if (entity !== undefined) parts.unshift(short(entity));
  return { head, rest: parts.join(' · ') };
}

function items(value: unknown): Item[] {
  return Array.isArray(value) ? value.filter((v): v is Item => !!v && typeof v === 'object') : [];
}

function Section({ label, list }: { label: string; list: Item[] }) {
  if (!list.length) return null;
  return (
    <div class="auto-sec">
      <span class="meta">{label}</span>
      <ul>{list.map((item, i) => { const l = line(item); return <li key={i}><b>{l.head}</b>{l.rest && <span> {l.rest}</span>}</li>; })}</ul>
    </div>
  );
}

function parsed(body: string): Config | null {
  try {
    const got: unknown = JSON.parse(body);
    return got && typeof got === 'object' && !Array.isArray(got) ? (got as Config) : null;
  } catch {
    return null;
  }
}

export function AutomationView({ body }: { body: string }) {
  const config = parsed(body);
  if (!config) return <div class="pbody plain"><p>{body}</p></div>;
  const triggers = items(config.triggers);
  const actions = items(config.actions);
  return (
    <div class="pbody auto">
      <p class="auto-name">{typeof config.alias === 'string' && config.alias.trim() ? config.alias : <span class="meta">No name yet</span>}
        {typeof config.mode === 'string' && <span class="pill">{config.mode}</span>}</p>
      {typeof config.description === 'string' && config.description && <p class="auto-desc">{config.description}</p>}
      {triggers.length ? <Section label="When" list={triggers} /> : <p class="meta">No trigger yet</p>}
      <Section label="Only if" list={items(config.conditions)} />
      {actions.length ? <Section label="Then" list={actions} /> : <p class="meta">No action yet</p>}
      <details class="auto-json"><summary class="meta">JSON</summary><pre><code>{JSON.stringify(config, null, 2)}</code></pre></details>
    </div>
  );
}
