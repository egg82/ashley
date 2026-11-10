// Whether the picker is open and on what: the list of what can be added, or one kind's form (to connect it, or to
// replace connection `replacing` when `base` is its address), or the rename of one.
import { signal } from '@preact/signals';
import type { ConnectionKindInfo, HouseholdConnection } from '../../api/types';
import { connectionsSaid } from './connections';

export type Picking =
  | { step: 'list' }
  | { step: 'form'; kind: ConnectionKindInfo; base: string; fromList: boolean; replacing?: number }
  | { step: 'rename'; connection: HouseholdConnection };

export const picking = signal<Picking | null>(null);

export function openList(): void {
  connectionsSaid.value = null;
  picking.value = { step: 'list' };
}

export function openForm(kind: ConnectionKindInfo, base: string, fromList: boolean, replacing?: number): void {
  connectionsSaid.value = null;
  picking.value = { step: 'form', kind, base, fromList, replacing };
}

export function openRename(connection: HouseholdConnection): void {
  connectionsSaid.value = null;
  picking.value = { step: 'rename', connection };
}

/** The picker closes with what the last change said left on the room. */
export function closePicker(): void {
  picking.value = null;
}

/** The person leaves the picker without connecting: a refusal it showed goes with it. */
export function cancelPicker(): void {
  connectionsSaid.value = null;
  closePicker();
}
