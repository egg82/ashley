// What she remembers about the signed-in person: what is new this week first, then the rest of theirs by kind, the
// household's as a second group, and the voiceprints she holds of them. Each fact opens in place to be corrected or
// forgotten; unknown reads as unknown, never as nothing. `PersonCard` is pure; `Person` reads when it first shows.
import { useEffect } from 'preact/hooks';
import type { MemoryFact, Voiceprint } from '../../api/types';
import { FactCard } from '../../rooms/memory/FactCard';
import { FactRow } from '../../rooms/memory/FactRow';
import { moment } from '../../rooms/memory/facts';
import { corrected } from '../../rooms/memory/memory';
import { Forget } from '../../rooms/memory/VoiceTab';
import { personView, printsOldestFirst } from './personView';
import type { PersonSource } from './sources';

const rows = (list: readonly MemoryFact[]) =>
  <div class="rows">{list.map((f) => <FactRow key={f.id} fact={f} fresh={corrected.value.has(f.id)} />)}</div>;

function Unknown({ what, source }: { what: string; source: PersonSource }) {
  return (
    <div class="k-person-unk" role="alert">
      <span class="unk">unknown</span>
      <span class="meta">Couldn't read {what} just now.</span>
      <button class="btn sm" type="button" onClick={() => void source.read()}>Try again</button>
    </div>
  );
}

export function PersonFacts({ source }: { source: PersonSource }) {
  const facts = source.facts.value;
  if (facts === undefined) return <p class="meta">Reading what she knows…</p>;
  if (facts === null) return <Unknown what="what she knows" source={source} />;
  if (!facts.length) return <p class="meta">She doesn't know anything about you yet. What she learns in conversations shows up here.</p>;
  const view = personView(facts, Date.now());
  return (
    <>
      {view.fresh.length > 0 && (
        <>
          <div class="sec-title"><b>New this week</b><span class="label">check these first</span></div>
          <div class="k-person-new">{view.fresh.map((f) => <FactCard key={f.id} fact={f} fresh={corrected.value.has(f.id)} />)}</div>
        </>
      )}
      {view.yours.length > 0 && (
        <>
          <div class="sec-title"><b>About you</b></div>
          {rows(view.yours)}
        </>
      )}
      {view.household.length > 0 && (
        <>
          <div class="sec-title"><b>The household's</b><span class="label">anyone here may hear these</span></div>
          {rows(view.household)}
        </>
      )}
    </>
  );
}

export function PersonPrints({ source }: { source: PersonSource }) {
  const prints: readonly Voiceprint[] | null | undefined = source.prints.value;
  if (prints === undefined) return <p class="meta">Reading her voiceprints…</p>;
  if (prints === null) return <Unknown what="your voiceprints" source={source} />;
  if (!prints.length) return <p class="meta">She doesn't know your voice.</p>;
  return (
    <>
      <div class="rows">
        {printsOldestFirst(prints).map((p, i) => (
          <div class="fact rem" data-kind="plan" key={i}>
            <span class="rem-when">{moment(p.enrolled_at)}</span>
            <span class="rem-what">Taken on {p.device}</span>
          </div>
        ))}
      </div>
      <Forget />
    </>
  );
}

export function PersonCard({ source }: { source: PersonSource }) {
  const prints = source.prints.value;
  return (
    <section class="k-person" aria-label="What she knows about you">
      <h2 class="label">What she knows about you</h2>
      <PersonFacts source={source} />
      <div class="sec-title">
        <b>Your voice</b>
        {prints && prints.length > 0 && <span class="label">{prints.length} {prints.length === 1 ? 'print' : 'prints'}</span>}
      </div>
      <PersonPrints source={source} />
    </section>
  );
}

export function Person({ source }: { source: PersonSource }) {
  useEffect(() => void source.read(), [source]);
  return <PersonCard source={source} />;
}
