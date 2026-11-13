import { useState } from 'preact/hooks';
import { setWord } from './lexiconWords';

export function AddWord() {
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
    <form class="cn-form hh-add" onSubmit={(e) => void submit(e)}>
      <label>
        <span class="meta">Word</span>
        <input type="text" value={real} maxLength={64} autocomplete="off" onInput={(e) => setReal(e.currentTarget.value)} />
      </label>
      <label>
        <span class="meta">Say it as</span>
        <input type="text" value={spoken} maxLength={64} autocomplete="off" onInput={(e) => setSpoken(e.currentTarget.value)} />
      </label>
      <button class="btn primary" type="submit" disabled={!real.trim() || !spoken.trim()}>Add</button>
    </form>
  );
}
