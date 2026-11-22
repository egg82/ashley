// A connection's settings changelog as the opened row lists it.
import type { SettingChange } from '../../../api/types';
import names from './settingNames.json' with { type: 'json' };

const NAMES: Record<string, string> = names;

function humanised(key: string): string {
  const text = key.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The changelog as lines: who changed which setting (null for a person who has since left), newest first. */
export function historyOf(changes: readonly SettingChange[]): { id: number; who: string | null; what: string; at: string }[] {
  return changes.map((c) => ({ id: c.id, who: c.edited_by?.name ?? null, what: (NAMES[c.key] ?? humanised(c.key)).toLowerCase(), at: c.changed_at }));
}
