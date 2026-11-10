// How an earlier conversation's divider reads: "Tuesday 7:42 pm" and "kitchen, voice". Pure reads of what the API
// returned; a conversation from before its channel was recorded has no "where", which the divider shows as an unknown.
import type { PastSummary } from '../../api/types';

const WEEK_DAYS = 6;

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** "Today 7:42 pm", "Yesterday 7:42 pm", "Tuesday 7:42 pm" within the week, else "Oct 24 7:42 pm". */
export function when(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).toLowerCase();
  const ago = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
  if (ago <= 0) return `Today ${time}`;
  if (ago === 1) return `Yesterday ${time}`;
  if (ago <= WEEK_DAYS) return `${d.toLocaleDateString('en-US', { weekday: 'long' })} ${time}`;
  const year = d.getFullYear() === now.getFullYear() ? undefined : 'numeric';
  return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year })} ${time}`;
}

/** "kitchen, voice", "Discord", "web"; null when the channel was not recorded. */
export function where(channel: PastSummary['channel'], place: string | null): string | null {
  switch (channel) {
    case 'voice': return place ? `${place}, voice` : 'voice';
    case 'device': return place ? `${place}, device` : 'device';
    case 'discord': return 'Discord';
    case 'web': return 'web';
    default: return null;
  }
}
