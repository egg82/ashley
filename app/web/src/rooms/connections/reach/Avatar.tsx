// A service's mark: its first letters on a tile whose hue comes from its kind, so the same service is the same colour everywhere.
function hueOf(kind: string): number {
  let h = 0;
  for (const ch of kind) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return 205 + (h % 50);
}

export function Avatar({ kind, title, ghost = false }: { kind: string; title: string; ghost?: boolean }) {
  const letters = title.replace(/[^A-Za-z]/g, '').slice(0, 2) || '?';
  return <span class={`rr-avatar${ghost ? ' ghost' : ''}`} style={{ '--hue': hueOf(kind) }} aria-hidden="true">{letters}</span>;
}
