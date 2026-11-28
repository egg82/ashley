// What the needs-attention part says, from `HouseAttention`: pure, so it is tested without a page. A part that cannot be
// read is listed as unknown, never folded into "nothing needs you"; only when every part reads clear does it say so.
import type { HouseAttention } from '../../api/types';

export interface AttentionLine {
  key: 'waiting' | 'printer' | 'house';
  text: string;
}

export interface AttentionView {
  /** What needs the person, worst first. */
  needs: AttentionLine[];
  /** What could not be read, by name. */
  unknown: AttentionLine[];
  /** Every part read, and none needs the person. */
  clear: boolean;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function attentionView(a: HouseAttention | null | undefined): AttentionView {
  const needs: AttentionLine[] = [];
  const unknown: AttentionLine[] = [];
  const waiting = a?.waiting_on_you ?? null;
  const printers = a?.printer_faults ?? null;
  const unreadable = a?.house_unreadable ?? null;
  if (waiting === null) unknown.push({ key: 'waiting', text: 'Waiting on you' });
  else if (waiting > 0) needs.push({ key: 'waiting', text: `${plural(waiting, 'thing', 'things')} waiting on you` });
  if (unreadable === null) unknown.push({ key: 'house', text: 'The house' });
  else if (unreadable) needs.push({ key: 'house', text: "The house isn't answering" });
  if (printers === null) unknown.push({ key: 'printer', text: 'Printers' });
  else if (printers > 0) needs.push({ key: 'printer', text: plural(printers, 'printer reports a fault', 'printers report a fault') });
  return { needs, unknown, clear: !needs.length && !unknown.length };
}
