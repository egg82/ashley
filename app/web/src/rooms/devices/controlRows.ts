// The edits to a draft list of a device's touch controls, and which devices carry them.
import type { CatalogueEntityInfo, ControlsRefused, DeviceControl, DeviceControlWanted, ListedDevice } from '../../api/types';

export const MOST = 12;
export const LABEL_MOST = 40;

/** Whether a device carries touch controls: a screen that reads text, which is neither a satellite, a Discord server nor the house. */
export function showsControls(d: ListedDevice): boolean {
  return d.form === 'other' && d.medium === 'text';
}

/** A draft row is a stored control, or a new one (`name` null) with nothing picked yet. */
export type Row = DeviceControlWanted;

export function draftOf(controls: DeviceControl[]): Row[] {
  return controls.map((c) => ({ name: c.name, label: c.label, action: c.action, entity_id: c.entity_id }));
}

export function added(rows: Row[], first: CatalogueEntityInfo | undefined): Row[] {
  if (rows.length >= MOST || !first) return rows;
  return [...rows, { name: null, label: first.name.slice(0, LABEL_MOST), action: 'light.turn_on', entity_id: first.entity_id }];
}

export function changed(rows: Row[], at: number, patch: Partial<Row>): Row[] {
  return rows.map((r, i) => (i === at ? { ...r, ...patch } : r));
}

export function removed(rows: Row[], at: number): Row[] {
  return rows.filter((_, i) => i !== at);
}

/** `rows` with the one at `at` moved by `by` places, kept in place when that would leave the list. */
export function moved(rows: Row[], at: number, by: -1 | 1): Row[] {
  const to = at + by;
  if (to < 0 || to >= rows.length) return rows;
  const out = [...rows];
  [out[at], out[to]] = [out[to]!, out[at]!];
  return out;
}

/** Whether every row has a label that fits and a light picked. */
export function complete(rows: Row[]): boolean {
  return rows.every((r) => r.label.trim().length >= 1 && r.label.trim().length <= LABEL_MOST && r.entity_id !== '');
}

/** The action that suits `entityId`'s domain: a scene can only be turned on, a light keeps an on or off already chosen. */
export function actionFor(entityId: string, action: Row['action']): Row['action'] {
  if (entityId.startsWith('scene.')) return 'scene.turn_on';
  return action === 'scene.turn_on' ? 'light.turn_on' : action;
}

/** What the picker calls a light or scene, so a person can tell them apart. */
export function pickName(e: CatalogueEntityInfo): string {
  return `${e.domain === 'scene' ? 'Scene' : 'Light'}: ${e.name}`;
}

export const REFUSED: Record<ControlsRefused['reason'], string> = {
  too_many: `A screen takes at most ${MOST} controls.`,
  bad_label: `Each label is 1 to ${LABEL_MOST} characters.`,
  bad_id: 'A control has a name she cannot use.',
  duplicate_id: 'Two controls have the same name.',
  unknown_entity: 'One of those lights or scenes is not in the house any more. Pick it again.',
  full: 'The screen has no room for another piece.',
  already_shown: 'The screen already has its controls.',
  required: 'The screen needs this piece to stay.',
};
