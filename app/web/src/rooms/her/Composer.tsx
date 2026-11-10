// The composer at the foot of her room, and of a bench's talk. Enter or Send sends and Shift+Enter starts a new line; it
// is one line at rest and grows as the person types. Send is off until there is something to send (1 to 4000
// characters, not only whitespace) and while her reply to the last message is still coming; past the limit nothing is cut,
// the count shows and Send waits (`limit.ts`). The talk button at its left sends what the person says instead
// (`speech/talk.ts`). What is typed and not sent is kept per thread (`unsent.ts`), so it is still here when the person
// comes back to the room. A paste longer than `PASTE_MIN` is not put in the box: it becomes a chip beside what is typed
// (`attached.ts`), which stays the message, and goes with it as one attachment (a piece on a bench, text she reads in
// chat); past `attachMax` the count shows and Send waits, as for the message.
import { useLayoutEffect, useRef, useState } from 'preact/hooks';
import type { Talk } from '../../speech/talk';
import { TalkButton, TalkLine } from '../../speech/TalkButton';
import { attachedOn, isLongPaste, pastedOn, unattachedOn } from './attached';
import { locale } from '../../household/format';
import { ATTACH_MAX, charCount, limitOf } from './limit';
import { sentOn, typedOn, unsentOn } from './unsent';

const WORDLESS = 'I pasted this.';

/** `thread` is the thread it sends on; `send` takes the trimmed text and the paste held with it, and answers why it was
 * not sent, when it was not; `talking` is the talk button's microphone; `ask` is the placeholder and label;
 * `attachMax` the longest paste it takes. */
export function Composer({ thread, disabled, send, talking, ask = 'Ask Ashley', attachMax = ATTACH_MAX }: {
  thread: string; disabled: boolean; send: (text: string, pasted: string | null) => Promise<string | null>; talking: Talk;
  ask?: string; attachMax?: number;
}) {
  const value = unsentOn(thread);
  const setValue = (text: string) => typedOn(thread, text);
  const pasted = attachedOn(thread);
  const [refused, setRefused] = useState<string | null>(null);
  const [held, setHeld] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const text = value.trim();
  const limit = limitOf(text);
  const pasteLength = pasted === null ? 0 : charCount(pasted);
  const pasteOver = pasteLength > attachMax;
  const ready = !disabled && (text.length > 0 || pasted !== null) && !limit.over && !pasteOver;
  useLayoutEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);
  return (
    <>
      <TalkLine talk={talking} held={held} />
      {limit.note && <p class={`compose-note${limit.over ? ' over' : ''}`} role={limit.over ? 'alert' : undefined}>{limit.note}</p>}
      {pasteOver && (
        <p class="compose-note over" role="alert">
          {`The paste is ${pasteLength.toLocaleString(locale())} / ${attachMax.toLocaleString(locale())}. Too long to send: cut ${(pasteLength - attachMax).toLocaleString(locale())}.`}
        </p>
      )}
      {refused && <p class="compose-note over" role="alert">{refused}</p>}
      {pasted !== null && (
        <div class="paste-chip">
          <span class="paste-chip-name">Pasted text</span>
          <span class="paste-chip-size">{pasteLength.toLocaleString(locale())} characters</span>
          <button class="paste-chip-x" type="button" aria-label="Remove the pasted text" onClick={() => unattachedOn(thread)}>{'\u00d7'}</button>
        </div>
      )}
      <form
        class={`compose${limit.over ? ' over' : ''}`}
        onSubmit={(e) => {
          e.preventDefault();
          if (!ready) return;
          const message = text || WORDLESS;
          sentOn(thread);
          unattachedOn(thread);
          setRefused(null);
          void send(message, pasted).then((why) => {
            if (why !== null) {
              typedOn(thread, text);
              if (pasted !== null) pastedOn(thread, pasted);
              setRefused(why);
            }
            input.current?.focus();
          });
        }}
      >
        <TalkButton talk={talking} disabled={disabled} onHeld={setHeld} />
        <textarea
          ref={input}
          rows={1}
          value={value}
          placeholder={ask}
          aria-label={ask}
          autocomplete="off"
          onInput={(e) => {
            setRefused(null);
            setValue(e.currentTarget.value);
          }}
          onPaste={(e) => {
            const got = e.clipboardData?.getData('text/plain') ?? '';
            if (!isLongPaste(got)) return;
            e.preventDefault();
            setRefused(null);
            pastedOn(thread, got);
          }}
          onKeyDown={(e) => {
            if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }}
        />
        <button class="btn primary" type="submit" disabled={!ready}>Send</button>
      </form>
    </>
  );
}
