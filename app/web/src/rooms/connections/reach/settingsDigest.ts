// A connection's settings as the opened row lists them: the ones that decide what she trusts, asks about or may read first,
// then preferences, each with how many things it holds and who last changed it, from the changelog.
import type { SettingChange, SettingEntry, SettingInfo } from '../../../api/types';
import names from './settingNames.json' with { type: 'json' };

const NAMES: Record<string, string> = names;

const DECIDES: Record<SettingInfo['decides'], string> = {
  taint: 'decides what she trusts',
  tier: 'decides what she asks about',
  read: 'decides what she may read',
  plain: 'a preference',
};

export interface DigestRow {
  key: string;
  title: string;
  decides: string;
  /** Whether it changes how she behaves, as against a preference. */
  judging: boolean;
  count: number;
  /** Who last changed it: a name (null for a person who has since left), or null when the changelog holds no change to it. */
  by: { name: string | null } | null;
  at: string | null;
}

function humanised(key: string): string {
  const text = key.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function countOf(entry: SettingEntry | undefined): number {
  return entry ? entry.ids.length + entry.per_action.reduce((n, a) => n + a.ids.length, 0) : 0;
}

/** `changes` is newest first, as the server gives them. */
export function digestOf(
  settings: readonly SettingInfo[],
  values: readonly SettingEntry[],
  changes: readonly SettingChange[],
): DigestRow[] {
  const rows = settings.map((s): DigestRow => {
    const last = changes.find((c) => c.key === s.key);
    return {
      key: s.key,
      title: NAMES[s.key] ?? humanised(s.key),
      decides: DECIDES[s.decides],
      judging: s.decides !== 'plain',
      count: countOf(values.find((v) => v.key === s.key)),
      by: last ? { name: last.edited_by?.name ?? null } : null,
      at: last?.changed_at ?? null,
    };
  });
  return [...rows.filter((r) => r.judging), ...rows.filter((r) => !r.judging)];
}

/** The changelog as lines: who changed which setting (null for a person who has since left), newest first. */
export function historyOf(changes: readonly SettingChange[]): { id: number; who: string | null; what: string; at: string }[] {
  return changes.map((c) => ({ id: c.id, who: c.edited_by?.name ?? null, what: (NAMES[c.key] ?? humanised(c.key)).toLowerCase(), at: c.changed_at }));
}
