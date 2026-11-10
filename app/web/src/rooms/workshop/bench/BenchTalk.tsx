// The bench's talk, beside its pieces: her room's lines and composer on the bench's own thread (`model/talk.ts`).
import { useLayoutEffect, useRef } from 'preact/hooks';
import { person } from '../../../session/session';
import { Composer } from '../../her/Composer';
import { Divider, Earlier } from '../../her/Earlier';
import { Thread } from '../../her/Thread';
import { useEarlier } from '../../her/useEarlier';
import { rules } from '../model/benches';
import {
  benchEarlier, benchTalking, retryTalk, sendTalk, talkConversation, talkLines, talkSending, talkStartedAt, talkState,
  talkThinking,
} from '../model/talk';

export function BenchTalk({ thread: talkThread, closed }: { thread: string; closed: boolean }) {
  const thread = useRef<HTMLDivElement>(null);
  const state = talkState.value;
  const shown = talkLines.value;
  const thinking = talkThinking.value;
  useLayoutEffect(() => {
    const el = thread.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown.length, thinking, state]);
  const open = talkConversation.value;
  const { before, reading, more, nearTop } = useEarlier(benchEarlier, thread, open, state === 'ready');
  const began = talkStartedAt.value ?? shown[0]?.at;
  return (
    <>
      <div class="thread wthread" ref={thread} aria-live="polite" onScroll={nearTop}>
        {state === 'loading' && <p class="chat-quiet meta">Reading…</p>}
        {(state === 'unreachable' || state === 'failed') && (
          <div class="chat-down" role="alert">
            <b>{state === 'failed' ? "What you've said here didn't load." : "Can't reach Ashley right now."}</b>
            <button class="btn" type="button" onClick={() => void retryTalk()}>Try again</button>
          </div>
        )}
        {state === 'ready' && <Earlier open={open} more={more} stream={benchEarlier} />}
        {state === 'ready' && before > 0 && began && shown.length > 0 && <Divider at={began} channel="web" place={null} />}
        {state === 'ready' && (
          <Thread lines={shown} name={person.value?.name ?? ''} thinking={thinking} conversation={open} />
        )}
        {state === 'ready' && reading !== 'loading' && before === 0 && !shown.length && !thinking && (
          <p class="chat-quiet meta">{closed ? 'Nothing was said here.' : "Ask her about what we're making here."}</p>
        )}
      </div>
      {!closed && (
        <Composer thread={talkThread} disabled={talkSending.value || state !== 'ready'} send={sendTalk} talking={benchTalking} ask="Ask Ashley about this"
          attachMax={rules.value?.kinds.find((k) => k.name === 'document')?.max_chars} />
      )}
    </>
  );
}
