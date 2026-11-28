// The talk ribbon at the bench's foot: a dot per line in the order said (hers brass, yours blue). A dot for her answer
// about a piece flies the canvas there; any other dot, or "Talk", opens the talk in order above it: her room's lines on
// the bench's own thread, earlier conversations, and what didn't send.
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { person } from '../../../session/session';
import { Divider, Earlier } from '../../her/Earlier';
import { Thread } from '../../her/Thread';
import { useEarlier } from '../../her/useEarlier';
import { focusAsk } from '../canvas/state';
import { ribbonOf, type Dot } from '../model/ribbon';
import { benchEarlier, retryTalk, talkConversation, talkLines, talkStartedAt, talkState, talkThinking } from '../model/talk';

function InOrder({ closed, at }: { closed: boolean; at: number | null }) {
  const box = useRef<HTMLDivElement>(null);
  const state = talkState.value;
  const shown = talkLines.value;
  const thinking = talkThinking.value;
  useLayoutEffect(() => {
    const el = box.current;
    const line = at === null ? null : el?.querySelector<HTMLElement>(`#turn-${at}`);
    if (line) line.scrollIntoView({ block: 'center' });
    else if (el) el.scrollTop = el.scrollHeight;
  }, [shown.length, thinking, state, at]);
  const open = talkConversation.value;
  const { before, reading, more, nearTop } = useEarlier(benchEarlier, box, open, state === 'ready');
  const began = talkStartedAt.value ?? shown[0]?.at;
  return (
    <div class="thread wthread rb-talk" ref={box} aria-live="polite" aria-label="The talk in order" onScroll={nearTop}>
      {state === 'loading' && <p class="chat-quiet meta">Reading…</p>}
      {(state === 'unreachable' || state === 'failed') && (
        <div class="chat-down" role="alert">
          <b>{state === 'failed' ? "What you've said here didn't load." : "Can't reach Ashley right now."}</b>
          <button class="btn" type="button" onClick={() => void retryTalk()}>Try again</button>
        </div>
      )}
      {state === 'ready' && <Earlier open={open} more={more} stream={benchEarlier} />}
      {state === 'ready' && before > 0 && began && shown.length > 0 && <Divider at={began} channel="web" place={null} />}
      {state === 'ready' && <Thread lines={shown} name={person.value?.name ?? ''} thinking={thinking} conversation={open} />}
      {state === 'ready' && reading !== 'loading' && before === 0 && !shown.length && !thinking && (
        <p class="chat-quiet meta">{closed ? 'Nothing was said here.' : 'Nothing said yet.'}</p>
      )}
    </div>
  );
}

function useDismiss(open: boolean, close: () => void): void {
  useEffect(() => {
    if (!open) return;
    const away = (e: Event) => !(e.target instanceof Element && e.target.closest('.ribbon')) && close();
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && close();
    document.addEventListener('pointerdown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('pointerdown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
}

/** `touched` is each of her turns' piece ids, `onBench` whether a piece is out on the bench. */
export function Ribbon({ closed, touched, onBench }: {
  closed: boolean; touched: ReadonlyMap<number, readonly number[]>; onBench: (id: number) => boolean;
}) {
  const [open, setOpen] = useState<{ at: number | null } | null>(null);
  useDismiss(open !== null, () => setOpen(null));
  const { dots, earlier } = ribbonOf(talkLines.value, touched, onBench);
  const tap = (d: Dot) => {
    if (d.piece === null) return setOpen({ at: d.turn ?? null });
    setOpen(null);
    focusAsk.value = d.piece;
  };
  return (
    <div class="ribbon">
      {open && <div class="rb-panel"><InOrder closed={closed} at={open.at} /></div>}
      <button class="label rb-open" type="button" aria-expanded={open !== null} onClick={() => setOpen(open ? null : { at: null })}>Talk</button>
      {earlier > 0 && <span class="meta rb-earlier">+{earlier}</span>}
      {dots.map((d) => (
        <button key={d.key} class={`rb-dot ${d.who}${d.missed ? ' missed' : ''}`} type="button" title={d.text}
          aria-label={`${d.who === 'her' ? 'Ashley' : 'You'}: ${d.text}`} onClick={() => tap(d)} />
      ))}
    </div>
  );
}
