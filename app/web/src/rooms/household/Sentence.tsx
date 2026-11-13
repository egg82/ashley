// The household's settings as one sentence she would say back, each setting a word to change in place.
import { household, householdSaid } from '../../household/household';
import { Slot } from './Slot';
import { draft } from './state';
import { localeGloss, sentenceOf, type SlotField } from './settingsSentence';

const LOCALES = ['en-US', 'en-GB', 'en-CA', 'en-AU', 'en-NZ', 'en-IE', 'fr-FR', 'fr-CA', 'de-DE', 'es-ES', 'es-MX', 'it-IT',
  'nl-NL', 'pt-BR', 'pt-PT', 'sv-SE', 'nb-NO', 'da-DK', 'fi-FI', 'pl-PL', 'ja-JP'];
const ZONES = Intl.supportedValuesOf('timeZone');

const REFUSED: Record<'timezone' | 'locale' | 'location', { text: string; slots: SlotField[] }> = {
  timezone: { text: 'Not a time zone she knows, so nothing was saved. Pick one from the list.', slots: ['timezone'] },
  locale: { text: 'Not a language and region she can use, so nothing was saved. Pick one from the list.', slots: ['locale'] },
  location: { text: 'Latitude and longitude go together, as degrees (latitude -90 to 90, longitude -180 to 180), so nothing was saved.',
    slots: ['latitude', 'longitude'] },
};

function Refused() {
  const said = householdSaid.value;
  if (said !== 'timezone' && said !== 'locale' && said !== 'location') return null;
  return <p class="hh-refused" role="alert">{REFUSED[said].text}</p>;
}

export function Sentence() {
  const d = draft.value;
  const h = household.value;
  if (!d || !h) return null;
  const said = householdSaid.value;
  const refused = said === 'timezone' || said === 'locale' || said === 'location' ? REFUSED[said].slots : [];
  const gloss = localeGloss(d.locale);
  return (
    <div class="panel hh-sentence">
      <div class="hh-head">
        <h2 class="hh-name">{h.name}</h2>
        <span class="meta">What she goes by here. Change a word and she changes with it.</span>
      </div>
      <p class="hh-said">
        {sentenceOf(d).map((part, i) => 'words' in part
          ? <span key={i}>{part.words}</span>
          : <Slot key={part.slot} field={part.slot} value={d[part.slot]} reads={part.reads}
              invalid={refused.includes(part.slot)} />)}
      </p>
      <p class="meta hh-gloss">{gloss ? `${d.locale} is ${gloss}.` : <span class="unk">this browser can't place that language and region</span>}</p>
      <Refused />
      <datalist id="hh-zones">{ZONES.map((z) => <option key={z} value={z} />)}</datalist>
      <datalist id="hh-locales">{LOCALES.map((l) => <option key={l} value={l} />)}</datalist>
    </div>
  );
}
