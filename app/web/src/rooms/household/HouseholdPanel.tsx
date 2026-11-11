// The household's own settings: its time zone, how it writes dates and times, the units she speaks in, where the house
// is, and what she always knows about it. Any person of the household may edit them.
import { useEffect, useState } from 'preact/hooks';
import type { Household, HouseholdRequest } from '../../api/types';
import { hour, locale } from '../../household/format';
import { degrees, parsePlace } from '../../household/place';
import { household, householdSaid, householdSaving, householdState, loadHousehold, saveHousehold } from '../../household/household';

const SAID: Record<NonNullable<typeof householdSaid.value>, [string, 'ok' | 'bad']> = {
  saved: ['Saved. She goes by it from her next reply.', 'ok'],
  timezone: ["Not a time zone she knows, so nothing was saved. Pick one from the list.", 'bad'],
  locale: ["Not a language and region she can use, so nothing was saved. Pick one from the list.", 'bad'],
  location: ['Latitude and longitude go together, as degrees (latitude -90 to 90, longitude -180 to 180), so nothing was saved.', 'bad'],
  failed: ["That didn't go through. Nothing changed.", 'bad'],
};

const LOCALES = ['en-US', 'en-GB', 'en-CA', 'en-AU', 'en-NZ', 'en-IE', 'fr-FR', 'fr-CA', 'de-DE', 'es-ES', 'es-MX', 'it-IT',
  'nl-NL', 'pt-BR', 'pt-PT', 'sv-SE', 'nb-NO', 'da-DK', 'fi-FI', 'pl-PL', 'ja-JP'];
const ZONES = Intl.supportedValuesOf('timeZone');
const SAMPLE = new Date(2026, 10, 10, 18, 5);

/** The request with the location as the two text boxes hold it. */
type Draft = Omit<HouseholdRequest, 'latitude' | 'longitude'> & { latitude: string; longitude: string };

/** How the draft would write a date, a time and a number, or null when the browser cannot read its locale. */
function sample(draft: Draft): string | null {
  try {
    const at = locale({ locale: draft.locale, clock: draft.clock });
    const day = SAMPLE.toLocaleDateString(at, { weekday: 'long', day: 'numeric', month: 'long' });
    const time = SAMPLE.toLocaleTimeString(at, { hour: hour({ locale: draft.locale, clock: draft.clock }), minute: '2-digit' });
    return `${day} · ${time} · ${(12345.5).toLocaleString(at)}`;
  } catch {
    return null;
  }
}

function Said() {
  const s = householdSaid.value;
  if (!s) return null;
  const [text, tone] = SAID[s];
  return (
    <div class={`dc-note ${tone}`} role={tone === 'bad' ? 'alert' : 'status'}>
      <span>{text}</span>
      <button class="btn sm ghost" type="button" onClick={() => (householdSaid.value = null)}>Dismiss</button>
    </div>
  );
}

function editable(h: Household): Draft {
  return {
    timezone: h.timezone, profile: h.profile, locale: h.locale, unit_system: h.unit_system, clock: h.clock,
    latitude: degrees(h.latitude), longitude: degrees(h.longitude),
  };
}

function Form({ h }: { h: Household }) {
  const [draft, setDraft] = useState<Draft>(editable(h));
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });
  const was = editable(h);
  const changed = (Object.keys(draft) as (keyof Draft)[]).some((k) => draft[k] !== was[k]);
  const shown = sample(draft);
  const submit = (e: Event) => {
    e.preventDefault();
    const place = parsePlace(draft.latitude, draft.longitude);
    if (typeof place === 'string') {
      householdSaid.value = 'location';
      return;
    }
    void saveHousehold({ ...draft, ...place, timezone: draft.timezone.trim(), locale: draft.locale.trim() });
  };
  return (
    <form class="cn-form hh-form" onSubmit={submit}>
      <div class="hh-grid">
        <label>
          <span class="meta">Time zone</span>
          <input type="text" list="hh-zones" value={draft.timezone} maxLength={64} autocomplete="off" spellcheck={false}
            onInput={(e) => set({ timezone: e.currentTarget.value })} />
        </label>
        <label>
          <span class="meta">Language and region</span>
          <input type="text" list="hh-locales" value={draft.locale} maxLength={35} autocomplete="off" spellcheck={false}
            onInput={(e) => set({ locale: e.currentTarget.value })} />
        </label>
        <label>
          <span class="meta">Clock</span>
          <select value={draft.clock} onChange={(e) => set({ clock: e.currentTarget.value as Draft['clock'] })}>
            <option value="24h">24-hour</option>
            <option value="12h">12-hour</option>
          </select>
        </label>
        <label>
          <span class="meta">Units</span>
          <select value={draft.unit_system}
            onChange={(e) => set({ unit_system: e.currentTarget.value as Draft['unit_system'] })}>
            <option value="imperial">Imperial: °F, miles, pounds</option>
            <option value="metric">Metric: °C, kilometres, kilograms</option>
          </select>
        </label>
      </div>
      <div class="hh-grid">
        <label>
          <span class="meta">Latitude</span>
          <input type="text" inputMode="decimal" value={draft.latitude} maxLength={24} autocomplete="off" spellcheck={false}
            placeholder="51.5072" onInput={(e) => set({ latitude: e.currentTarget.value })} />
        </label>
        <label>
          <span class="meta">Longitude</span>
          <input type="text" inputMode="decimal" value={draft.longitude} maxLength={24} autocomplete="off" spellcheck={false}
            placeholder="-0.1276" onInput={(e) => set({ longitude: e.currentTarget.value })} />
        </label>
      </div>
      <p class="meta hh-sample">Where the house is, in degrees, for finding places near it. It is used before Home Assistant's own, and only a rounded point leaves her. Leave both blank for none.</p>
      <p class="meta hh-sample">{shown ? `Written as ${shown}` : <span class="unk">this browser can't write that language and region</span>}</p>
      <label>
        <span class="meta">What she always knows about the household</span>
        <textarea value={draft.profile} maxLength={h.profile_limit} rows={6}
          placeholder="Who lives here, their pronouns, the pets, what the calendars and lists are called"
          onInput={(e) => set({ profile: e.currentTarget.value })} />
        <span class="meta hh-count">{draft.profile.length.toLocaleString(locale())} / {h.profile_limit.toLocaleString(locale())}</span>
      </label>
      <div class="dc-act">
        <button class="btn primary" type="submit" disabled={!changed || householdSaving.value}>Save</button>
        {changed && <button class="btn sm ghost" type="button" onClick={() => setDraft(editable(h))}>Undo</button>}
      </div>
      <datalist id="hh-zones">{ZONES.map((z) => <option key={z} value={z} />)}</datalist>
      <datalist id="hh-locales">{LOCALES.map((l) => <option key={l} value={l} />)}</datalist>
    </form>
  );
}

function Body() {
  const h = household.value;
  if (householdState.value === 'failed' && !h) {
    return (
      <div class="devs-body">
        <span class="unk">couldn't read the household</span>
        <button class="btn sm ghost" type="button" onClick={() => void loadHousehold()}>Try again</button>
      </div>
    );
  }
  if (!h) return <div class="devs-body"><span class="meta">Reading the household…</span></div>;
  return <Form key={JSON.stringify(h)} h={h} />;
}

export function HouseholdPanel() {
  useEffect(() => () => void (householdSaid.value = null), []);
  return (
    <div class="panel devs">
      <div class="ph"><h3>This household</h3></div>
      <div class="dc-body">
        <Body />
        <Said />
      </div>
    </div>
  );
}
