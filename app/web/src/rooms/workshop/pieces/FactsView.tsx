// A facts piece read as a table: each value with its unit and where it came from. A `guessed` row is hatched, as
// an unknown is elsewhere, so what still needs measuring stands out.
// A choice row (`kind: "choice"`, what kind of thing something is) shows its label and its value in words.
// A body that is not the shape is shown as the text it is. Edited as JSON in the ordinary editor.
type Row = {
  name: string; label?: string; value: number | string; unit?: string; source: string; tolerance?: number; ref?: string;
};

const SOURCES = ['measured', 'stated', 'seen', 'datasheet', 'accepted', 'bound', 'guessed'];

function rowOf(raw: unknown): Row | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const { kind, name, label, value, unit, source, tolerance, ref } = r;
  if (typeof name !== 'string' || typeof source !== 'string') return null;
  const choice = kind === 'choice' && typeof label === 'string' && typeof value === 'string';
  if (!choice && (kind !== undefined || typeof value !== 'number' || typeof unit !== 'string')) return null;
  return {
    name, source,
    value: value as number | string,
    label: choice ? (label as string) : undefined,
    unit: choice ? undefined : (unit as string),
    tolerance: typeof tolerance === 'number' ? tolerance : undefined,
    ref: typeof ref === 'string' && ref ? ref : undefined,
  };
}

function rowsOf(body: string): Row[] | null {
  try {
    const got: unknown = JSON.parse(body);
    const items = got && typeof got === 'object' ? (got as { items?: unknown }).items : null;
    if (!Array.isArray(items)) return null;
    const rows = items.map(rowOf);
    return rows.every((r): r is Row => r !== null) ? rows : null;
  } catch {
    return null;
  }
}

// A name wraps only after an underscore, never inside a word.
function Name({ name }: { name: string }) {
  return <>{name.split('_').flatMap((part, i, all) => (i < all.length - 1 ? [part, '_', <wbr key={i} />] : [part]))}</>;
}

export function FactsView({ body }: { body: string }) {
  const rows = rowsOf(body);
  if (!rows) return <div class="pbody plain"><p>{body}</p></div>;
  if (!rows.length) return <div class="pbody"><span class="meta">No facts yet.</span></div>;
  return (
    <div class="pbody meas">
      <table>
        <thead><tr><th>Name</th><th class="num">Value</th><th>Source</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <th scope="row" title={r.ref}>{r.label ?? <Name name={r.name} />}</th>
              {r.unit === undefined ? <td>{r.value}</td> : (
                <td class="num">
                  {r.value}
                  {r.tolerance ? <span class="meta"> ±{r.tolerance}</span> : null} <span class="meta">{r.unit}</span>
                </td>
              )}
              <td>
                <span class="meas-src" data-source={SOURCES.includes(r.source) ? r.source : 'guessed'}>{r.source}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.some((r) => r.ref) && (
        <ul class="meas-refs">
          {rows.filter((r) => r.ref).map((r) => <li key={r.name}><b>{r.label ?? <Name name={r.name} />}</b> <span class="meta">{r.ref}</span></li>)}
        </ul>
      )}
    </div>
  );
}
