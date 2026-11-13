// A session piece followed while it is on screen: its body names one of the person's Claude Code sessions, and the
// page asks the server for that session's screen, again after the wait each answer gives, and not at all while the page
// is hidden. The last screen stays shown when the bridge stops answering or the session ends.
import type { SessionScreen } from '../../../api/sessions';

export type ScreenState = SessionScreen['state'];
export type ScreenStatus = NonNullable<SessionScreen['status']>;

/** What the piece shows: the state of the last answer, the session's status and screen from the last `live` one
 *  (empty before any), and whether that screen left older lines out. */
export type Shown = { state: ScreenState; status: ScreenStatus | null; text: string; truncated: boolean };

const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** How long to wait after a request that failed in the page (offline, signed out) before asking again. */
export const FAILED_MS = 20000;

/** The session a piece's body names, or null for a body that is not a session reference (the server checks bodies, but
 *  an id goes into a URL, so the page checks it too). */
export function sessionOf(body: string): string | null {
  try {
    const got: unknown = JSON.parse(body);
    if (!got || typeof got !== 'object' || Array.isArray(got)) return null;
    const { source, session } = got as Record<string, unknown>;
    return source === 'herdr' && typeof session === 'string' && ID.test(session) ? session : null;
  } catch {
    return null;
  }
}

export type Follow = {
  read: (session: string, seen: string | null, signal: AbortSignal) => Promise<SessionScreen>;
  wait: (ms: number, signal: AbortSignal) => Promise<void>;
  visible: () => boolean;
  shown: (signal: AbortSignal) => Promise<void>;
};

/** Ask for `session`'s screen until `signal` aborts, calling `show` after each answer. */
export async function follow(session: string, show: (s: Shown) => void, deps: Follow, signal: AbortSignal): Promise<void> {
  let seen: string | null = null;
  let last: Shown = { state: 'live', status: null, text: '', truncated: false };
  while (!signal.aborted) {
    if (!deps.visible()) {
      await deps.shown(signal);
      continue;
    }
    let again = FAILED_MS;
    try {
      const got = await deps.read(session, seen, signal);
      again = got.again_ms;
      if (got.state === 'live') {
        seen = got.digest ?? null;
        last = { state: 'live', status: got.status ?? null, text: got.text ?? last.text, truncated: got.text === null ? last.truncated : got.truncated };
      } else {
        seen = null;
        last = { ...last, state: got.state };
      }
    } catch {
      if (signal.aborted) return;
      seen = null;
      last = { ...last, state: 'unreachable' };
    }
    show(last);
    await deps.wait(again, signal);
  }
}

/** `follow`'s needs in a browser: fetch, a timer, and the page's visibility. */
export function browserFollow(read: Follow['read']): Follow {
  return {
    read,
    wait: (ms, signal) => new Promise((done) => {
      const timer = setTimeout(done, ms);
      signal.addEventListener('abort', () => { clearTimeout(timer); done(); }, { once: true });
    }),
    visible: () => document.visibilityState === 'visible',
    shown: (signal) => new Promise((done) => {
      const back = () => { if (document.visibilityState === 'visible') finish(); };
      const finish = () => { document.removeEventListener('visibilitychange', back); done(); };
      document.addEventListener('visibilitychange', back);
      signal.addEventListener('abort', finish, { once: true });
    }),
  };
}
