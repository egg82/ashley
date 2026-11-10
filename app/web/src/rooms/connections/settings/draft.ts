// A connection's settings as the page edits them: ids by setting key, and for an entity-per-action setting by action.
// Pure, so what changed and what is sent are tested without the page.
import type { SettingEntry } from '../../../api/types';

export type Draft = Record<string, Record<string, string[]>>;

/** The key under which a plain list of ids is held. */
export const LIST = '';

export function draftOf(entries: readonly SettingEntry[]): Draft {
  const draft: Draft = {};
  for (const e of entries) {
    draft[e.key] = e.per_action.length > 0 ? Object.fromEntries(e.per_action.map((a) => [a.action, [...a.ids]])) : { [LIST]: [...e.ids] };
  }
  return draft;
}

/** The draft as the request carries it: a key with nothing picked is left out. */
export function entriesOf(draft: Draft): SettingEntry[] {
  return Object.entries(draft).flatMap(([key, lists]): SettingEntry[] => {
    const picked = Object.entries(lists).filter(([, ids]) => ids.length > 0);
    if (picked.length === 0) return [];
    if (LIST in lists) return [{ key, ids: lists[LIST] ?? [], per_action: [] }];
    return [{ key, ids: [], per_action: picked.map(([action, ids]) => ({ action, ids })) }];
  });
}

/** `ids` of `key` (under `action` for an entity-per-action setting). */
export function idsOf(draft: Draft, key: string, action: string = LIST): readonly string[] {
  return draft[key]?.[action] ?? [];
}

/** The draft with `ids` of `key` (under `action`) replaced. */
export function withIds(draft: Draft, key: string, action: string, ids: readonly string[]): Draft {
  return { ...draft, [key]: { ...draft[key], [action]: [...ids] } };
}

export function toggled(ids: readonly string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id];
}

/** Whether `a` and `b` send the same request. */
export function same(a: Draft, b: Draft): boolean {
  return JSON.stringify(entriesOf(a)) === JSON.stringify(entriesOf(b));
}
