// How a page tells the server whether it is in the foreground (`POST /api/screens/visibility`, the kiosk's
// `POST /api/kiosk/screen`). The page makes a token at load, opens its live feed under it (`?screen=`) and reports
// against it, so any pod of either site can say which screens are open and being looked at. It reports once the feed is
// up, on every change of the Page Visibility API's state, and every `REPORT_MS` while the feed is up, since a lost
// report is corrected by the next. Nothing is reported while the feed is down: there is no open screen to name.
import { effect } from '@preact/signals';

/** How often a visible or hidden page repeats its report while its feed is up. */
export const REPORT_MS = 30_000;

/** This page load's name for its screen: a random version-4 UUID. */
export const screenToken: string = makeToken();

function makeToken(): string {
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6]! & 0x0f) | 0x40;
  b[8] = (b[8]! & 0x3f) | 0x80;
  const hex = Array.from(b, (n) => n.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** What a report needs of the browser, so it can be driven without one. */
export interface Page {
  /** Whether the page is in the foreground now. */
  visible(): boolean;
  /** Calls `heard` on every change of visibility; returns the unsubscribe. */
  onChange(heard: () => void): () => void;
  /** Calls `tick` every `ms`; returns the stop. */
  every(tick: () => void, ms: number): () => void;
}

export const browserPage: Page = {
  visible: () => document.visibilityState === 'visible',
  onChange(heard) {
    document.addEventListener('visibilitychange', heard);
    return () => document.removeEventListener('visibilitychange', heard);
  },
  every(tick, ms) {
    const timer = setInterval(tick, ms);
    return () => clearInterval(timer);
  },
};

export interface Reporting {
  /** Starts reporting while `up` is true, unless it has started. */
  start(): void;
  /** Stops, and reports nothing more. */
  stop(): void;
}

/** Reports `page`'s visibility through `send` whenever `up` holds, as described above. A report that fails is dropped:
 * the next one says the same. */
export function createReporting(up: { readonly value: boolean }, send: (visible: boolean) => Promise<unknown>,
                                page: Page = browserPage): Reporting {
  let stopEffect: (() => void) | undefined;
  const report = (): void => void send(page.visible()).catch(() => undefined);
  return {
    start() {
      if (stopEffect) return;
      stopEffect = effect(() => {
        if (!up.value) return;
        report();
        const stops = [page.onChange(report), page.every(report, REPORT_MS)];
        return () => stops.forEach((stop) => stop());
      });
    },
    stop() {
      stopEffect?.();
      stopEffect = undefined;
    },
  };
}
