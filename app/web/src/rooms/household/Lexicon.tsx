// The household's pronunciation words: how the voice should say a word it gets wrong, any person of the household may edit.
import { useState } from 'preact/hooks';
import { lexiconSaid, lexiconState, limit, loadLexicon, removeWord, setWord, words } from './lexiconWords';

const SAID: Record<NonNullable<typeof lexiconSaid.value>, string> = {
  not_a_word: 'The word must be one word, letters with at most apostrophes and hyphens.',
  blank_spelling: 'Type how it should be said.',
  too_long: 'The word and its spelling are each at most 64 characters.',
  full: 'The household has the most words it can hold. Remove one first.',
  failed: "That didn't go through. Nothing changed.",
};

function Add() {
  const [real, setReal] = useState('');
  const [spoken, setSpoken] = useState('');
  const submit = async (e: Event) => {
    e.preventDefault();
    if (await setWord(real.trim(), spoken.trim())) {
      setReal('');
      setSpoken('');
    }
  };
  return (
    <form class="cn-form lx-add" onSubmit={(e) => void submit(e)}>
      <label>
        <span class="meta">Word</span>
        <input type="text" value={real} maxLength={64} autocomplete="off" onInput={(e) => setReal(e.currentTarget.value)} />
      </label>
      <label>
        <span class="meta">Said as</span>
        <input type="text" value={spoken} maxLength={64} autocomplete="off" onInput={(e) => setSpoken(e.currentTarget.value)} />
      </label>
      <button class="btn primary" type="submit" disabled={!real.trim() || !spoken.trim()}>Add</button>
    </form>
  );
}

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
      return words.value.length ? (
        <>
          {words.value.map((w) => (
            <div key={w.real} class="acct-row">
              <span><b>{w.real}</b> <span class="meta">said as</span> <b>{w.spoken}</b></span>
              <button class="btn sm ghost" type="button" onClick={() => void removeWord(w.real)}>Remove</button>
            </div>
          ))}
        </>
      ) : (
        <div class="devs-body"><p class="meta">No words yet. She says everything as it is spelled.</p></div>
      );
  }
}

export function Lexicon() {
  return (
    <div class="panel devs">
      <div class="ph"><h3>How she says words</h3></div>
      <Words />
      <div class="dc-body">
        <Said />
        <Add />
        {lexiconState.value === 'ready' && <p class="meta">Applies to her spoken replies, from the next one. Up to {limit.value} words.</p>}
      </div>
    </div>
  );
}
