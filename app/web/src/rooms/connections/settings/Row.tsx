// One row of a section: the name a person knows the thing by, its raw id as small secondary text, and the control.
import type { ComponentChildren } from 'preact';

export function Row({ name, sub, note, children }: { name: string; sub: string; note?: string | null; children: ComponentChildren }) {
  return (
    <li class="set-row">
      <span class="set-row-name">
        <span>{name}</span>
        <span class="meta">{sub}</span>
        {note && <span class="meta set-note">{note}</span>}
      </span>
      <span class="set-toggles">{children}</span>
    </li>
  );
}
