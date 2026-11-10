// "Things that need your word": what she changes after reading an email or web page only if the person asked, picked by
// searching the house. A thing she handles that way anyway is shown as Already.
import { useState } from 'preact/hooks';
import { idsOf, toggled, withIds } from './draft';
import { found, needLines, type House } from './house';
import { Example } from './Example';
import { Row } from './Row';
import { draft, edit } from './state';

const KEY = 'consequential_entities';

function change(id: string): void {
  edit(withIds(draft.value, KEY, '', toggled(idsOf(draft.value, KEY), id)));
}

function Search({ house, listed }: { house: House; listed: readonly string[] }) {
  const [query, setQuery] = useState('');
  const { shown, more } = found(house, query, listed);
  return (
    <div class="set-search">
      <input class="cn-search" type="search" value={query} placeholder="Search the house to add something" aria-label="Search the house"
        autocomplete="off" onInput={(e) => setQuery(e.currentTarget.value)} />
      {shown.length > 0 && (
        <ul class="set-pick">
          {shown.map((t) => (
            <li key={t.id}>
              <span><span>{t.name}</span> <span class="meta">{t.id}{t.sub ? ` · ${t.sub}` : ''}</span></span>
              {t.already
                ? <span class="pill cn-tag" title="She handles this with care anyway, so listing it changes nothing">Already</span>
                : <button class="btn sm" type="button" onClick={() => change(t.id)}>Add</button>}
            </li>
          ))}
        </ul>
      )}
      {more > 0 && <p class="meta">{more} more; search to narrow.</p>}
      {query.trim() !== '' && house !== null && shown.length === 0 && <p class="meta">Nothing matches “{query.trim()}”.</p>}
    </div>
  );
}

export function NeedWordSection({ house }: { house: House }) {
  const ids = idsOf(draft.value, KEY);
  const lines = needLines(house, ids);
  return (
    <section class="panel cn-set">
      <div class="cn-set-head"><h2>Things that need your word</h2></div>
      <p class="cn-blurb">After she reads an email or web page, she changes these only if you asked her to.</p>
      <Example cases={[
        { does: false, text: 'An email says “turn off the server rack”. A plain switch normally just happens. With the server rack listed here, she leaves it on and tells you the email asked.' },
      ]} />
      {lines.length === 0
        ? <p class="set-empty">Nothing listed. Locks, garage doors and alarms are already handled this way, so they need no entry.</p>
        : (
          <ul class="set-rows">
            {lines.map((l) => (
              <Row key={l.id} name={l.name} sub={l.id} note={l.missing ? 'Not in Home Assistant right now' : l.already ? 'Already handled this way, so this entry changes nothing' : null}>
                <button class="btn sm ghost" type="button" aria-label={`Remove ${l.name}`} onClick={() => change(l.id)}>Remove</button>
              </Row>
            ))}
          </ul>
        )}
      <Search house={house} listed={ids} />
    </section>
  );
}
