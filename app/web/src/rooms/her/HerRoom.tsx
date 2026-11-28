// Her room, at the centre of the field, laid out as the Desk: the board on the left, the conversation in the middle and
// the house on the right on wide screens, a fixed grid; below that width the board and the house fold into toggles above
// the conversation. The conversation is her mark and state on top, the open conversation on the person's web thread
// below it, and the composer at the foot. Scrolling up past the open conversation reads the person's earlier ones in
// above it, read only, under a divider each. At phone width the same parts are laid out as the Pocket (`desk/Pocket.tsx`).
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import { Vis } from '../../components/FactParts';
import { PHONE, useMedia } from '../../components/useMedia';
import { watchHouse } from '../../session/house';
import { person } from '../../session/session';
import { herState, herWord } from '../../shell/her/state';
import {
  conversationId, enterRoom, leaveRoom, lines, loadChat, loadState, send, sending, startedAt, talking, threadThinking,
} from './chat';
import { Composer } from './Composer';
import { Board } from './board/Board';
import { Folds } from './desk/Folds';
import { House } from './desk/House';
import { Pocket } from './desk/Pocket';
import { watchWork } from './work';
import { Divider, Earlier } from './Earlier';
import { chatEarlier, earlierReset } from './past';
import { Thread } from './Thread';
import { useEarlier } from './useEarlier';

/** Wide enough for the Desk's three columns. */
const DESK_WIDE = '(min-width: 1200px)';

function Down({ failed }: { failed: boolean }) {
  return (
    <div class="chat-down" role="alert">
      <b>{failed ? "What you've said to her didn't load." : "Can't reach Ashley right now."}</b>
      <button class="btn" type="button" onClick={() => void loadChat()}>Try again</button>
    </div>
  );
}

export function HerRoom() {
  useEffect(() => {
    earlierReset();
    enterRoom();
    const stopWork = watchWork();
    const stopHouse = watchHouse();
    return () => {
      stopWork();
      stopHouse();
      leaveRoom();
    };
  }, []);
  const state = loadState.value;
  const shown = lines.value;
  const her = herState.value;
  const thinking = threadThinking.value;
  const thread = useRef<HTMLDivElement>(null);
  // A new line, or her starting to think here, keeps the newest at the foot in view.
  useLayoutEffect(() => {
    const el = thread.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown.length, thinking]);
  const open = conversationId.value;
  const ready = state === 'ready';
  const began = startedAt.value ?? shown[0]?.at;
  const { before, reading, more, nearTop } = useEarlier(chatEarlier, thread, open, ready);
  const wide = useMedia(DESK_WIDE);
  const phone = useMedia(PHONE);
  const pane = (
    <div class="thread" ref={thread} aria-live="polite" onScroll={nearTop}>
      {state === 'loading' && <p class="chat-quiet meta">Reading…</p>}
      {(state === 'unreachable' || state === 'failed') && <Down failed={state === 'failed'} />}
      {ready && <Earlier open={open} more={more} />}
      {ready && before > 0 && began && <Divider at={began} channel="web" place={null} />}
      {ready && <Thread lines={shown} name={person.value?.name ?? ''} thinking={thinking} conversation={open} />}
      {ready && reading !== 'loading' && before === 0 && !shown.length && !thinking && (
        <p class="chat-quiet meta">Nothing yet. Whatever you say to her, here or anywhere else, shows up here.</p>
      )}
    </div>
  );
  const composer = { thread: `person:${person.value?.id ?? 0}:web`, disabled: sending.value || state !== 'ready', send, talking };
  return (
    <div class={`desk${wide ? ' wide' : ''}`}>
      {wide && <aside class="desk-col desk-board" aria-label="Board"><Board open={open} /></aside>}
      <div class="her-room">
        <div class="chat-her">
          <span class="chat-dock" data-dock />
          <span class={`her-word${her === 'unreachable' ? ' unreachable' : ''}`}>{herWord.value}</span>
          <Vis v="private" />
        </div>
        {phone ? <Pocket open={open} thread={pane} composer={composer} /> : (
          <>
            {!wide && <Folds open={open} />}
            {pane}
            <Composer {...composer} />
          </>
        )}
      </div>
      {wide && <aside class="desk-col desk-house" aria-label="House"><House /></aside>}
    </div>
  );
}
