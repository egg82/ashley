// Correct in place (T11): the fact's text becomes an input. Enter saves, Escape cancels; Save is off until the text
// is a change the server would take (1 to 1000 characters, not only whitespace).
import { useEffect, useRef, useState } from 'preact/hooks';

const MAX = 1000;

interface Props {
  text: string;
  saving: boolean;
  onSave: (text: string) => void;
  onCancel: () => void;
}

export function CorrectEditor({ text, saving, onSave, onCancel }: Props) {
  const [value, setValue] = useState(text);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  const next = value.trim();
  const ready = !saving && next.length > 0 && next !== text.trim();
  return (
    <form
      class="edit"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) onSave(next);
      }}
    >
      <input
        ref={input}
        value={value}
        maxLength={MAX}
        aria-label="What the fact should say"
        disabled={saving}
        onInput={(e) => setValue(e.currentTarget.value)}
        onKeyDown={(e) => e.key === 'Escape' && onCancel()}
      />
      <button class="btn sm primary" type="submit" disabled={!ready}>{saving ? 'Saving' : 'Save'}</button>
      <button class="btn sm ghost" type="button" disabled={saving} onClick={onCancel}>Cancel</button>
    </form>
  );
}
