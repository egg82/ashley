// Which kiosk parts are read on a timer. The glance is read always, since nothing announces a person coming or going, and a toggle's light is read with it;
// the conversation and the layout only while the live feed is down, since the feed says when they change.

export type Part = 'conversation' | 'glance' | 'layout';

/** How often each part is read when it is read on a timer. */
export const POLL_MS: Record<Part, number> = { conversation: 15_000, glance: 60_000, layout: 60_000 };

/** Whether `part` is read on its timer, given whether the live feed is up. */
export function polled(part: Part, feedUp: boolean): boolean {
  return part === 'glance' || !feedUp;
}
