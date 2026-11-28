// The trust setting's rows as the screen draws them: the choice in force, and why a locked row cannot be changed.
import type { TrustRow } from '../../api/types';

export type Pick = { kind: string; value: TrustRow['value'] };

const LOCKED: Record<NonNullable<TrustRow['locked']>, string> = {
  asks: 'She always asks you first.',
  irreversible: "This can't be undone, so she always asks first.",
};

export function lockedLine(row: TrustRow): string | null {
  return row.locked ? LOCKED[row.locked] : null;
}

/** The whole choice a save sends: every row as it stands, with one kind set to `value`. */
export function picksWith(rows: TrustRow[], kind: string, value: TrustRow['value']): Pick[] {
  return rows.map((r) => ({ kind: r.kind, value: r.kind === kind ? value : r.value }));
}
