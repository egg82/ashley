// A live feed's connection: an EventSource reopened with backoff when it drops, one `LiveEvent` per message, and a
// `resync` call whenever what is shown may be out of date (the feed opened, or told the screen it fell behind). The
// person's feed (`live.ts`) and the kiosk's (`kiosk/live.ts`) differ only in the route they open and what they do
// with what they hear.
import { signal } from '@preact/signals';
import type { LiveEvent } from '../api/types';

const FIRST_WAIT_MS = 1000;
const MAX_WAIT_MS = 30000;

export interface Feed {
  /** Whether the feed is open; while it is not, nothing it would have said is heard. */
  up: { readonly value: boolean };
  /** Opens the feed, unless it is open or opening. */
  open(): void;
  /** Closes the feed and stops reopening it. */
  close(): void;
}

/** A feed over `connect`'s EventSource. `heard` gets each event but `resync`, which has its own callback; `lost` is
 * called when an open feed drops. */
export function createFeed(
  connect: () => EventSource,
  on: { heard: (event: Exclude<LiveEvent, { type: 'resync' }>) => void; resync: () => void; lost: () => void },
): Feed {
  const up = signal(false);
  let source: EventSource | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let waitMs = FIRST_WAIT_MS;
  let wanted = false;

  function drop(): void {
    source?.close();
    source = undefined;
    if (up.value) on.lost();
    up.value = false;
  }

  function reach(): void {
    retry = undefined;
    const opened = connect();
    source = opened;
    opened.onopen = () => {
      waitMs = FIRST_WAIT_MS;
      up.value = true;
      on.resync();
    };
    opened.onmessage = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as LiveEvent;
      if (event.type === 'resync') on.resync();
      else on.heard(event);
    };
    // The browser's own retry would keep a 401 or 503 going at its pace; this one backs off.
    opened.onerror = () => {
      drop();
      if (!wanted) return;
      retry = setTimeout(reach, waitMs * (0.75 + Math.random() / 2));
      waitMs = Math.min(waitMs * 2, MAX_WAIT_MS);
    };
  }

  return {
    up,
    open() {
      wanted = true;
      if (source || retry) return;
      reach();
    },
    close() {
      wanted = false;
      clearTimeout(retry);
      retry = undefined;
      drop();
    },
  };
}
