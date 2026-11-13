// One editable word of the settings sentence: a choice for the clock and the units, typed text for the rest.
import { edit } from './state';
import { CLOCKS, type SlotField, UNITS } from './settingsSentence';
import type { Draft } from './draft';

const TEXT: Record<'timezone' | 'locale' | 'latitude' | 'longitude', { label: string; max: number; list?: string; numeric?: boolean }> = {
  timezone: { label: 'time zone', max: 64, list: 'hh-zones' },
  locale: { label: 'language and region', max: 35, list: 'hh-locales' },
  latitude: { label: 'latitude', max: 24, numeric: true },
  longitude: { label: 'longitude', max: 24, numeric: true },
};

/** `value` is what the draft holds; `reads` how the sentence says it. */
export function Slot({ field, value, reads, invalid }: { field: SlotField; value: string; reads: string; invalid: boolean }) {
  if (field === 'clock') {
    return (
      <select class="hh-slot" aria-label="clock" value={value}
        onChange={(e) => edit({ clock: e.currentTarget.value as Draft['clock'] })}>
        {CLOCKS.map((c) => <option key={c.value} value={c.value}>{c.reads}</option>)}
      </select>
    );
  }
  if (field === 'unit_system') {
    return (
      <select class="hh-slot" aria-label="units" value={value}
        onChange={(e) => edit({ unit_system: e.currentTarget.value as Draft['unit_system'] })}>
        {UNITS.map((u) => <option key={u.value} value={u.value}>{u.reads}</option>)}
      </select>
    );
  }
  const t = TEXT[field];
  return (
    <input class="hh-slot" type="text" aria-label={t.label} placeholder={t.label} value={reads} maxLength={t.max} list={t.list}
      inputMode={t.numeric ? 'decimal' : undefined} autocomplete="off" spellcheck={false} aria-invalid={invalid || undefined}
      onInput={(e) => edit({ [field]: e.currentTarget.value })} />
  );
}
