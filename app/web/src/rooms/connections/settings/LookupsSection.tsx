// "When she looks something up": each script or action is one of three choices; the ones that make changes fold away
// behind a search.
import { useState } from 'preact/hooks';
import { idsOf, withIds } from './draft';
import type { House, LookupLine } from './house';
import { lookupLines } from './house';
import { CHOICES, type Choice, type Stored, withChoice } from './lookups';
import { Example } from './Example';
import { Row } from './Row';
import { draft, edit } from './state';

const SHOWN = 8;
const OPTIONS: readonly Choice[] = ['changes', 'finds_out', 'finds_out_trusted'];

function stored(): Stored {
  return { reads: idsOf(draft.value, 'reads'), service: idsOf(draft.value, 'service_reads') };
}

function pick(line: LookupLine, choice: Choice): void {
  const next = withChoice(line.id, choice, stored(), line.fixed);
  edit(withIds(withIds(draft.value, 'reads', '', next.reads), 'service_reads', '', next.service));
}

function Choose({ line }: { line: LookupLine }) {
  const options = line.fixed ? OPTIONS.filter((o) => o !== 'changes') : OPTIONS;
  return (
    <select class={`set-choice${line.choice === 'changes' ? '' : ' on'}`} aria-label={`What ${line.name} does`} value={line.choice}
      onChange={(e) => pick(line, e.currentTarget.value as Choice)}>
      {options.map((o) => <option key={o} value={o}>{CHOICES[o]}</option>)}
    </select>
  );
}

function LookupRow({ line }: { line: LookupLine }) {
  const note = line.missing ? 'Not in Home Assistant right now' : line.fixed ? 'Home Assistant says it only finds things out' : null;
  return <Row name={line.name} sub={line.id} note={note}><Choose line={line} /></Row>;
}

function Others({ lines }: { lines: LookupLine[] }) {
  const [query, setQuery] = useState('');
  const words = query.trim().toLowerCase();
  const hits = words ? lines.filter((l) => `${l.name} ${l.id}`.toLowerCase().includes(words)) : lines.slice(0, SHOWN);
  return (
    <details class="cn-fold">
      <summary>{lines.length === 1 ? '1 more script makes changes' : `${lines.length} more scripts make changes`}</summary>
      <div>
        <input class="cn-search" type="search" value={query} placeholder="Search scripts" aria-label="Search scripts" autocomplete="off"
          onInput={(e) => setQuery(e.currentTarget.value)} />
        <ul class="set-rows">{hits.map((l) => <LookupRow key={l.id} line={l} />)}</ul>
        {!words && lines.length > SHOWN && <p class="meta">{lines.length - SHOWN} more; search to find one.</p>}
        {words && hits.length === 0 && <p class="meta">Nothing matches “{query.trim()}”.</p>}
      </div>
    </details>
  );
}

export function LookupsSection({ house }: { house: House }) {
  const lines = lookupLines(house, stored());
  const finding = lines.filter((l) => l.choice !== 'changes');
  const changing = lines.filter((l) => l.choice === 'changes');
  return (
    <section class="panel cn-set">
      <div class="cn-set-head"><h2>When she looks something up</h2></div>
      <Example cases={[
        { does: true, text: 'You ask “How long to drive to the airport?” She runs a travel-time script. It only finds something out, so she runs it even in the middle of reading an email.' },
        { does: true, text: 'Its answer comes from a maps service you trust, so afterwards she carries on as normal.' },
        { does: false, text: 'A script not marked as finding something out counts as a change. In the middle of an email she waits for your OK first.' },
      ]} />
      <p class="cn-blurb">Pick “I trust the answer” only when nobody outside your household can put words into it, like a drive time from your maps.</p>
      {finding.length === 0
        ? <p class="set-empty">No script is marked as finding something out.</p>
        : <ul class="set-rows">{finding.map((l) => <LookupRow key={l.id} line={l} />)}</ul>}
      {changing.length > 0 && <Others lines={changing} />}
    </section>
  );
}
