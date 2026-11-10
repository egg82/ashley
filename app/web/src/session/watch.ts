// Keeps an open page on the server's build: remembers the build it booted on, asks `/api/health` for the served one on
// each resync and on a slow timer, and reloads at a quiet moment (`update.ts` decides).
import { getHealth } from '../api/client';
import { counted, decide, type Tries } from './update';

/** How often the served build is asked for, besides on a resync. */
const CHECK_MS = 5 * 60_000;
/** How often a quiet moment is looked for once a newer build is known. */
const QUIET_CHECK_MS = 5_000;
const TRIES_KEY = 'ashley.update.tries';

function storage(): Storage | null {
  try {
    return sessionStorage;
  } catch {
    return null;
  }
}

function readTries(store: Storage): Tries {
  try {
    return JSON.parse(store.getItem(TRIES_KEY) ?? '{}') as Tries;
  } catch {
    return {};
  }
}

/** Whether the page itself is being served now; a reload into an error page would strand the screen. */
async function servable(): Promise<boolean> {
  try {
    const r = await fetch(location.href, { cache: 'no-store', redirect: 'manual', signal: AbortSignal.timeout(10_000) });
    return r.ok || r.type === 'opaqueredirect';
  } catch {
    return false;
  }
}

export interface Watch {
  /** Asks for the served build now. */
  check(): void;
  stop(): void;
}

/** Starts watching; `held()` is true while a reload would cut something off. */
export function watchBuild(held: () => boolean = () => false): Watch {
  const store = storage();
  let booted: string | null = null;
  let served: string | null = null;
  let lastInput = 0;
  let interacted = false;
  let going = false;

  const touch = (): void => {
    lastInput = Date.now();
    interacted = true;
  };
  const events = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart'] as const;
  events.forEach((n) => addEventListener(n, touch, { capture: true, passive: true }));

  async function reload(): Promise<void> {
    if (!store || served === null) return;
    going = true;
    if (!(await servable())) {
      going = false;
      return;
    }
    if (held()) {
      going = false;
      return;
    }
    try {
      store.setItem(TRIES_KEY, JSON.stringify(counted(readTries(store), served, Date.now())));
    } catch {
      // no storage: a roll could loop, so do not reload
      going = false;
      return;
    }
    location.reload();
  }

  function consider(): void {
    if (going || !store || document.hidden) return;
    const now = Date.now();
    const verdict = decide({ booted, served, tries: readTries(store), now, idleMs: now - lastInput, interacted, held: held() });
    if (verdict === 'reload') void reload();
  }

  async function check(): Promise<void> {
    try {
      served = (await getHealth()).version;
    } catch {
      return;
    }
    booted ??= served;
    consider();
  }

  void check();
  const slow = setInterval(() => void check(), CHECK_MS);
  const quiet = setInterval(consider, QUIET_CHECK_MS);
  return {
    check: () => void check(),
    stop() {
      clearInterval(slow);
      clearInterval(quiet);
      events.forEach((n) => removeEventListener(n, touch, { capture: true }));
    },
  };
}
