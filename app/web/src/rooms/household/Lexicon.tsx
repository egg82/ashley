// The household's pronunciation words as a card: each word and how she should say it. Any person of the household may edit them.
import { useEffect } from 'preact/hooks';
import { AddWord } from './AddWord';
import { WordRow } from './WordRow';
import { lexiconSaid, lexiconState, limit, loadLexicon, words } from './lexiconWords';

const SAID: Record<NonNullable<typeof lexiconSaid.value>, string> = {
  not_a_word: 'The word must be one word, letters with at most apostrophes and hyphens.',
  blank_spelling: 'Type how it should be said.',
  too_long: 'The word and its spelling are each at most 64 characters.',
  full: 'The household has the most words it can hold. Remove one first.',
  failed: "That didn't go through. Nothing changed.",
};

function Said() {
  const s = lexiconSaid.value;
  if (!s) return null;
  return (
    <div class="dc-note bad" role="alert">
      <span>{SAID[s]}</span>
      <button class="btn sm ghost" type="button" onClick={() => (lexiconSaid.value = null)}>Dismiss</button>
    </div>
  );
}

function Words() {
  switch (lexiconState.value) {
    case 'loading':
      return <div class="devs-body"><span class="meta">Reading the words…</span></div>;
    case 'failed':
      return (
        <div class="devs-body">
          <span class="unk">couldn't read the words</span>
          <button class="btn sm ghost" type="button" onClick={() => void loadLexicon()}>Try again</button>
        </div>
      );
    case 'ready':
      return words.value.length
        ? <>{words.value.map((w) => <WordRow key={w.real} word={w} />)}</>
        : <div class="devs-body"><p class="meta">No words yet. She says everything as it is spelled.</p></div>;
  }
}

export function Lexicon() {
  useEffect(() => () => void (lexiconSaid.value = null), []);
  const ready = lexiconState.value === 'ready';
  return (
    <section class="panel hh-lex" aria-labelledby="hh-lex-h">
      <div class="ph">
        <h3 id="hh-lex-h">Say it right</h3>
        {ready && <span class="meta hh-lex-count">{words.value.length} of {limit.value}</span>}
      </div>
      <Words />
      <div class="dc-body">
        <Said />
        {ready && <AddWord />}
        {ready && <p class="meta">Applies to her spoken replies, from the next one.</p>}
      </div>
    </section>
  );
}
