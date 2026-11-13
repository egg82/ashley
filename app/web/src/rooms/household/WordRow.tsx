// One pronunciation word: the word, how she says it (editable here), who set it and when, and a way to remove it.
import { useState } from 'preact/hooks';
import type { LexiconWord } from '../../api/types';
import { locale } from '../../household/format';
import { removeWord, setWord } from './lexiconWords';

export function WordRow({ word }: { word: LexiconWord }) {
  const [spoken, setSpoken] = useState(word.spoken);
  const changed = spoken.trim() !== '' && spoken.trim() !== word.spoken;
  const on = new Date(word.updated_at).toLocaleDateString(locale(), { month: 'short', day: 'numeric' });
  const save = (e: Event) => {
    e.preventDefault();
    if (changed) void setWord(word.real, spoken.trim());
  };
  return (
    <form class="hh-word" onSubmit={save}>
      <b class="hh-real">{word.real}</b>
      <label class="hh-say">
        <span class="label">Say</span>
        <input type="text" value={spoken} maxLength={64} autocomplete="off" aria-label={`How she says ${word.real}`}
          onInput={(e) => setSpoken(e.currentTarget.value)} />
      </label>
      <span class="meta hh-by">{word.edited_by ? `${word.edited_by.name}, ${on}` : <span class="unk">not recorded</span>}</span>
      <span class="hh-word-acts">
        {changed && <button class="btn sm primary" type="submit">Save</button>}
        <button class="btn sm ghost" type="button" aria-label={`Remove ${word.real}`} onClick={() => void removeWord(word.real)}>Remove</button>
      </span>
    </form>
  );
}
