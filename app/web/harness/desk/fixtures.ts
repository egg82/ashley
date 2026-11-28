// Made-up data for the Desk harness: a board with every lane and action, a short conversation, the house. The names are
// a fixture household's, nobody's real ones; the longest titles are long on purpose.
import type { HouseAttention, HouseGlance, KioskControl } from '../../src/api/types';
import type { BoardItem } from '../../src/rooms/her/board/offers';

const at = (h: number, m = 0) => new Date(Date.UTC(2026, 10, 27, h, m)).toISOString();
const OPEN = 31;

export const CONVERSATION_ID = OPEN;

export const WORK: BoardItem[] = [
  { kind: 'proposal', id: 11, title: 'Turn the heating down 2° tomorrow, 9 to 5, while everyone is out', state: 'waiting_on_you', lane: 'waiting', at: at(9, 58), conversation_id: OPEN, can_tap: true },
  { kind: 'proposal', id: 12, title: 'Delete the automation "Porch light at dusk"', state: 'waiting_on_you', lane: 'waiting', at: at(9, 40), conversation_id: OPEN, can_tap: false },
  { kind: 'proposal', id: 13, title: 'Which pharmacy for the refill?', state: 'waiting_on_you', lane: 'waiting', at: at(8, 10), conversation_id: 7, can_tap: false },
  { kind: 'watch', id: 40, title: 'Watching for the pump to ship', state: 'running', lane: 'doing', at: at(7), can_tap: false },
  { kind: 'open_errand', id: 41, title: 'Finding a cheaper internet plan', state: 'running', lane: 'doing', at: at(10, 2), until_local: '2026-11-28T17:00', can_tap: false },
  { kind: 'watch', id: 42, title: 'Watching the build of the sensor firmware until it passes', state: 'stopped', lane: 'doing', at: at(6, 30), can_tap: false },
  { kind: 'bench', id: 5, title: 'Balcony watering', state: 'open', lane: 'doing', at: at(10, 2), can_tap: false },
  { kind: 'action', id: 71, title: 'Turned on the porch light', state: 'done', lane: 'on_her_own', at: at(17, 48), cause: { kind: 'watch', id: 40 }, undo: null, can_tap: false, can_undo: false },
  { kind: 'action', id: 72, title: 'Put 4 mm pump tubing (2 m) on the Hardware list', state: 'done', lane: 'on_her_own', at: at(7, 58), cause: { kind: 'bench', id: 5 }, undo: { kind: 'todo_remove', ref: '4 mm pump tubing', within: 'todo.hardware' }, can_tap: false, can_undo: true },
  { kind: 'action', id: 73, title: 'Added an automation: "Close the garage at 22:00 when nobody is in the garage and the door has been open for more than ten minutes"', state: 'done', lane: 'on_her_own', at: at(9, 12), cause: { kind: 'wake', id: 900 }, undo: { kind: 'house_delete', ref: 'automation.garage_close', within: 'automation' }, can_tap: false, can_undo: true },
  { kind: 'action', id: 74, title: 'Labelled 3 mails from the school', state: 'done', lane: 'on_her_own', at: at(8, 2), cause: { kind: 'turn', id: 3 }, undo: { kind: 'reminder_cancel', ref: '9', within: null }, can_tap: false, can_undo: false, undone: { at: at(8, 30), how: 'undone' } },
  { kind: 'errand', id: 81, title: 'Firmware rerun: dry now reads 412', state: 'done', lane: 'done_untold', at: at(10, 2), can_tap: false },
  { kind: 'errand', id: 91, title: 'Not worth raising: the bins went out a day early', state: 'done', lane: 'kept_quiet' as BoardItem['lane'], at: at(6), can_tap: false },
];

const ATTENTION: Record<string, HouseAttention> = {
  needs: { waiting_on_you: 3, printer_faults: null, house_unreadable: false },
  zero: { waiting_on_you: 0, printer_faults: 0, house_unreadable: false },
  unknown: { waiting_on_you: null, printer_faults: null, house_unreadable: null },
};

export function glanceOf(kind: string): HouseGlance {
  return { home: kind === 'unknown' ? null : ['Maya', 'Theo', 'Jonah'], needs_attention: ATTENTION[kind] ?? ATTENTION.needs! };
}

export const CONTROLS: KioskControl[] = [
  { name: 'living-lights', label: 'Living room', on: true },
  { name: 'porch-light', label: 'Porch', on: false },
  { name: 'kitchen-lights', label: 'Kitchen', on: null },
  { name: 'movie-night', label: 'Movie night', on: null },
  { name: 'all-off', label: 'Everything off', on: null },
];

function turn(id: number, author: 'person' | 'ashley', text: string, minute: number) {
  return { id, author, text, at: at(9, minute), follows: false, continued_on: null, attachment: null, runs: [], looks: [], working: false, agree: null, voiced: false, receipts: null, agreed: null, piece_ids: [] };
}

export const CONVERSATION = {
  thread: 'person:1:web',
  conversation_id: OPEN,
  started_at: at(9, 50),
  turns: [
    turn(1, 'person', 'Did the sensor thing ever get sorted?', 50),
    turn(2, 'ashley', 'Yes. It read 1023 when dry because the sensor pin had no pull-down. I added one to the wiring and reran: dry now reads 412.', 51),
    turn(3, 'person', 'Is it going to rain Saturday?', 55),
    turn(4, 'ashley', "Dry until about 4. Everyone's out 9 to 5 tomorrow, so I'd like to turn the heating down 2° while the house is empty.", 58),
  ],
};
