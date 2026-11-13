// The edits to a draft list of a device's touch controls.
import type { CatalogueEntityInfo, ControlsRefused, DeviceControl, DeviceControlWanted } from '../../api/types';

export const MOST = 12;
export const LABEL_MOST = 40;

/** A draft row is a stored control, or a new one (`name` null) with nothing picked yet. */
export type Row = DeviceControlWanted;

export function draftOf(controls: DeviceControl[]): Row[] {
  return controls.map((c) => ({ name: c.name, label: c.label, action: c.action, entity_id: c.entity_id }));
}

/** `rows` with a new control for `entity` at `at` (the end by default); a scene is turned on, a light toggled. */
export function added(rows: Row[], entity: CatalogueEntityInfo | undefined, at: number = rows.length): Row[] {
  if (rows.length >= MOST || !entity) return rows;
  const row: Row = { name: null, label: entity.name.slice(0, LABEL_MOST), action: actionFor(entity.entity_id, 'light.toggle'), entity_id: entity.entity_id };
  return [...rows.slice(0, at), row, ...rows.slice(at)];
}

/** `rows` with the one at `from` taken out and put where `to` says, counted before it was taken out. */
export function reordered(rows: Row[], from: number, to: number): Row[] {
  const row = rows[from];
  if (!row || to < 0 || to > rows.length) return rows;
  const out = rows.filter((_, i) => i !== from);
  out.splice(to > from ? to - 1 : to, 0, row);
  return out;
}

/** Whether the draft differs from what is stored, in what is shown, in what order and in what each does. */
export function dirty(rows: Row[], stored: DeviceControl[]): boolean {
  return rows.length !== stored.length || rows.some((r, i) => {
    const c = stored[i]!;
    return r.name !== c.name || r.label !== c.label || r.action !== c.action || r.entity_id !== c.entity_id;
  });
}

/** What a control does, as the drawn button names it. */
export const DOES: Record<Row['action'], string> = { 'light.toggle': 'Toggle', 'light.turn_on': 'Turn on', 'light.turn_off': 'Turn off', 'scene.turn_on': 'Run scene' };

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

/** The action that suits `entityId`'s domain: a scene can only be turned on, a light keeps the action already chosen, and takes toggle from a scene. */
export function actionFor(entityId: string, action: Row['action']): Row['action'] {
  if (entityId.startsWith('scene.')) return 'scene.turn_on';
  return action === 'scene.turn_on' ? 'light.toggle' : action;
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
