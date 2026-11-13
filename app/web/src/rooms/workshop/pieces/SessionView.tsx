// A session piece: one of the person's Claude Code sessions, its screen shown as it runs (`model/session.ts`), kept
// scrolled to its newest line unless the person has scrolled up to read.
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { sessionScreen } from '../../../api/sessions';
import { browserFollow, follow, sessionOf, type ScreenState, type ScreenStatus, type Shown } from '../model/session';

const STATUS: Record<ScreenStatus, string> = { idle: 'Idle', working: 'Working', blocked: 'Waiting for you', done: 'Done', unknown: 'Running' };
const NOT_LIVE: Record<Exclude<ScreenState, 'live'>, string> = {
  gone: 'This session has ended.',
  not_connected: 'Connect your Claude Code bridge in Connections to see this session.',
  unreachable: "Can't reach your machine right now. Trying again.",
  refused: 'Your bridge turned this connection away. Check it in Connections.',
};
const FOLLOW = browserFollow(sessionScreen);

function Screen({ text }: { text: string }) {
  const box = useRef<HTMLPreElement>(null);
  const pinned = useRef(true);
  useLayoutEffect(() => {
    const el = box.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [text]);
  const scrolled = () => {
    const el = box.current;
    if (el) pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 8;
  };
  return <pre class="session-screen" ref={box} tabIndex={0} aria-label="Session output" onScroll={scrolled}>{text}</pre>;
}

export function SessionView({ body }: { body: string }) {
  const session = sessionOf(body);
  const [shown, setShown] = useState<Shown | null>(null);
  useEffect(() => {
    if (!session) return;
    setShown(null);
    const stop = new AbortController();
    void follow(session, setShown, FOLLOW, stop.signal);
    return () => stop.abort();
  }, [session]);
  if (!session) return <div class="pbody plain"><p>{body}</p></div>;
  if (!shown) return <div class="pbody session"><span class="meta">Reading the session…</span></div>;
  const live = shown.state === 'live';
  return (
    <div class="pbody session" data-state={shown.state}>
      <p class="rline">
        {live && shown.status && <span class={`rstate${shown.status === 'done' ? ' ok' : ''}`}>{STATUS[shown.status]}</span>}
        {shown.state === 'live' ? <span class="meta"> · Claude Code{shown.truncated ? ' · latest lines' : ''}</span> : <span class="meta">{NOT_LIVE[shown.state]}</span>}
      </p>
      {shown.text && <Screen text={shown.text} />}
    </div>
  );
}
