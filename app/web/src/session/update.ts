// When a page that is already open should reload because the server runs a newer build. Pure: `watch.ts` holds the
// browser. The build is `GET /api/health`'s `version`; a local run reports `dev` and never reloads.

/** How long without a pointer, touch or key before a page that was touched at all counts as quiet. */
export const QUIET_MS = 20_000;
/** After a reload for a build that is still not the one served (a pod still on the old image), how long to wait before
 * the next try, by tries so far; past the last, the page gives up on that build. */
export const BACKOFF_MS: readonly number[] = [10 * 60_000, 60 * 60_000];
export const DEV = 'dev';

/** The reloads already made for a served build. */
export type Tries = Readonly<Record<string, { at: number; count: number }>>;

export type Verdict = 'current' | 'wait' | 'reload' | 'backoff' | 'gave-up';

export interface Facts {
  /** The build the page booted on; null until the first answer. */
  booted: string | null;
  /** The build last served; null until an answer. */
  served: string | null;
  tries: Tries;
  now: number;
  idleMs: number;
  /** Whether anything has touched the page since it loaded; an untouched wall display reloads at once. */
  interacted: boolean;
  /** Something a reload would cut: a recording, a message going out. */
  held: boolean;
}

export function decide(f: Facts): Verdict {
  if (!f.booted || !f.served || f.booted === DEV || f.served === DEV || f.booted === f.served) return 'current';
  const tried = f.tries[f.served];
  if (tried) {
    if (tried.count > BACKOFF_MS.length) return 'gave-up';
    if (f.now - tried.at < BACKOFF_MS[tried.count - 1]!) return 'backoff';
  }
  if (f.held) return 'wait';
  if (f.interacted && f.idleMs < QUIET_MS) return 'wait';
  return 'reload';
}

/** `tries` with one more reload counted for `served`. */
export function counted(tries: Tries, served: string, now: number): Tries {
  return { ...tries, [served]: { at: now, count: (tries[served]?.count ?? 0) + 1 } };
}
