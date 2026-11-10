// The one line a connection's card says of its settings, counted from what is stored.
import type { SettingEntry } from '../../../api/types';

function count(n: number, one: string, many: string): string {
  return n === 0 ? `no ${many}` : `${n} ${n === 1 ? one : many}`;
}

function idsOf(values: readonly SettingEntry[], key: string): string[] {
  const entry = values.find((v) => v.key === key);
  return entry ? [...entry.ids, ...entry.per_action.flatMap((a) => a.ids)] : [];
}

/** Lists she counts as the household's, things she looks up, and things that need the person's word. Home Assistant's own look-ups (not scripts) count when trusted. */
export function summaryOf(values: readonly SettingEntry[]): string {
  const lookups = new Set([...idsOf(values, 'reads'), ...idsOf(values, 'service_reads').filter((id) => !id.startsWith('script.'))]);
  const needs = idsOf(values, 'consequential_entities').length;
  return [count(idsOf(values, 'household_reads').length, 'list', 'lists'), count(lookups.size, 'look-up', 'look-ups'),
          needs === 0 ? 'nothing that needs your word' : `${needs} that need${needs === 1 ? 's' : ''} your word`].join(', ');
}
