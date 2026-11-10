// The kiosk's conversation and its composer. Lines are her room's (`Thread`); whoever typed here is named by the place.
// The talk button at the composer's left sends what was said instead (`speech/talk.ts`).
import { useLayoutEffect, useRef, useState } from 'preact/hooks';
import { limitOf } from '../rooms/her/limit';
import { Thread } from '../rooms/her/Thread';
import { TalkButton, TalkLine } from '../speech/TalkButton';
import { device, lines, mark, send, sending, talking } from './state';

function placeName(place: string | undefined): string {
  return place ? place.slice(0, 1).toUpperCase() + place.slice(1) : 'Here';
}

function Composer() {
  const [value, setValue] = useState('');
  const [held, setHeld] = useState(false);
  const text = value.trim();
  const limit = limitOf(text);
  const ready = !sending.value && text.length > 0 && !limit.over;
  return (
    <>
      <TalkLine talk={talking} held={held} />
      {limit.note && <p class={`compose-note${limit.over ? ' over' : ''}`} role={limit.over ? 'alert' : undefined}>{limit.note}</p>}
      <form
        class={`compose k-compose${limit.over ? ' over' : ''}`}
        onSubmit={(e) => {
          e.preventDefault();
          if (!ready) return;
          setValue('');
          void send(text);
        }}
      >
        <TalkButton talk={talking} disabled={sending.value} onHeld={setHeld} />
        <input
          value={value}
          placeholder="Talk to Ashley"
          aria-label="Message"
          autocomplete="off"
          onInput={(e) => setValue(e.currentTarget.value)}
        />
        <button class="btn primary" type="submit" disabled={!ready}>Send</button>
      </form>
    </>
  );
}

export function Talk() {
  const shown = lines.value;
  const thinking = mark.value === 'thinking';
  const thread = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = thread.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown.length, thinking]);
  return (
    <section class="k-talk" aria-label="Conversation">
      <div class="thread" ref={thread} aria-live="polite">
        <Thread lines={shown} name={placeName(device.value?.place)} thinking={thinking} conversation={null} />
      </div>
      <Composer />
    </section>
  );
}
