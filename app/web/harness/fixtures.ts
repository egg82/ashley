// Made-up benches for looking at the bench canvas without a server: 5, 11 or 32 pieces of mixed kinds, links of every
// kind, a pin and a box, and her lines on some pieces (one just said, the rest older). The numbers and words are
// invented; only their shape is the API's.
import type { BenchDetail, BenchLink, BenchPiece, ChatConversation, WorkshopKinds } from '../src/api/types';

export const KINDS: WorkshopKinds = {
  kinds: [
    { name: 'document', family: 'stored', label: 'Document', max_chars: 200000, format: 'markdown', language: null },
    { name: 'note', family: 'stored', label: 'Note', max_chars: 4000, format: 'plain', language: null },
    { name: 'code', family: 'stored', label: 'Code', max_chars: 50000, format: 'code', language: 'python' },
    { name: 'automation', family: 'stored', label: 'Automation', max_chars: 50000, format: 'automation', language: null },
  ],
  link_kinds: [
    { name: 'part_of', label: 'part of' }, { name: 'depends_on', label: 'depends on' }, { name: 'version_of', label: 'version of' },
  ] as unknown as WorkshopKinds['link_kinds'],
  max_pieces: 60,
  title_max_chars: 120,
  run_languages: ['python'],
  run_max_chars: 50000,
  work_kinds: [],
};

const NOTE = 'Water the balcony boxes when the soil is dry, not on a timer. Two boxes, one pump, one sensor each.';
const DOC = '## Plan\n\nThe sensor reads every **10 minutes** and publishes `dry` over MQTT when it crosses the line.\n\n- pump bracket printed in PETG\n- 4 mm tubing, 2 m\n- automation installs once the sensor reads true for a week';
const CODE = '# soil moisture: "dry" over MQTT\nraw = adc.read(0)\nif raw > DRY:\n    mqtt.publish("balcony/soil", "dry")\nsleep(600)';
const AUTO = JSON.stringify({ alias: 'Water when dry', triggers: [{ trigger: 'state', entity_id: 'sensor.balcony_soil', to: 'dry' }], conditions: [{ condition: 'state', entity_id: 'weather.home', state: 'sunny' }], actions: [{ action: 'switch.turn_on', target: { entity_id: 'switch.pump' } }] });

interface Seed { kind: string; title: string; body: string }

const SEEDS: Seed[] = [
  { kind: 'document', title: 'Plan', body: DOC },
  { kind: 'code', title: 'Sensor firmware', body: CODE },
  { kind: 'note', title: 'Pump bracket v3', body: 'Cracked at the tab after a week in the sun. Tab wall 3.0 mm.' },
  { kind: 'automation', title: 'Water when dry', body: AUTO },
  { kind: 'note', title: 'Pump bracket v4', body: 'Tab wall 5.0 mm, fillet on the inside corner. Print check passes at 18 g.' },
  { kind: 'note', title: 'Tubing', body: 'On the hardware list: 4 mm, 2 m. Theo says the kitchen drawer is out.' },
  { kind: 'document', title: 'Measurements', body: '| what | value |\n|---|---|\n| pipe | 4 mm |\n| tab wall | 3.0 mm |\n| sun on rail | ~55 °C |' },
  { kind: 'note', title: 'Wiring', body: 'ESP32 → 10k pull-down → MOSFET → pump. Sensor on GPIO 34.' },
  { kind: 'code', title: 'Calibration script', body: 'readings = [adc.read(0) for _ in range(30)]\nprint(min(readings), max(readings))' },
  { kind: 'note', title: 'Pump datasheet', body: '5 V, 240 mA, 1.2 L/min. Runs dry for 30 s at most.' },
  { kind: 'note', title: 'Firmware build notes, and why the second board refused to flash on Tuesday', body: 'Hold BOOT while plugging in. The cable matters.' },
];

const EXTRA = ['Drip line layout', 'Box two sensor', 'Rain check', 'Overflow tray', 'Sun hours log', 'MQTT topics', 'Enclosure lid', 'Cable glands',
  'Power budget', 'Winter plan', 'Mount screws', 'Second pump?', 'Leak test', 'Valve option', 'Reservoir size', 'Timer fallback', 'Alerts',
  'Battery backup', 'Soil types', 'Seed list', 'Box three', 'Calibration log'];

function seedsFor(n: number): Seed[] {
  const out = SEEDS.slice(0, Math.min(n, SEEDS.length));
  for (let i = out.length; i < n; i++) out.push({ kind: i % 3 === 0 ? 'code' : 'note', title: EXTRA[(i - SEEDS.length) % EXTRA.length]!, body: i % 3 === 0 ? CODE : NOTE });
  return out;
}

function piece(id: number, s: Seed, order: number, ago: number): BenchPiece {
  const at = new Date(Date.now() - ago * 60_000).toISOString();
  return {
    id, kind: s.kind, title: s.title, body: s.body, piece_version: 1, placement: { order, pin: null, box: null },
    changed_by: id, changed_at: at, changed_author: id % 2 ? 'ashley' : 'person', changed_person_id: id % 2 ? null : 1,
    last_run: null, automation: null, video: null, reader: null, pointer: null, file: null, site: null, recipe: null, wake: null,
  } as BenchPiece;
}

/** Links for `n` pieces with ids 1..n: the five seeded relations, then each later piece part of (or depending on) an
 *  earlier one, with a few cross links. */
function linksFor(n: number): BenchLink[] {
  const base: [number, string, number][] = [[2, 'part_of', 1], [3, 'part_of', 1], [4, 'part_of', 1], [5, 'version_of', 3], [4, 'depends_on', 2],
    [6, 'part_of', 1], [7, 'depends_on', 3], [8, 'part_of', 2], [9, 'depends_on', 2], [10, 'depends_on', 4], [11, 'part_of', 2]];
  const out = base.filter(([a, , b]) => a <= n && b <= n).map(([from_id, kind, to_id]) => ({ from_id, kind, to_id }));
  for (let i = 12; i <= n; i++) {
    out.push({ from_id: i, kind: i % 5 === 0 ? 'depends_on' : 'part_of', to_id: 1 + ((i * 7) % (i - 1)) });
    if (i % 6 === 0) out.push({ from_id: i, kind: 'depends_on', to_id: 2 + (i % 5) });
    if (i === 20) out.push({ from_id: 20, kind: 'version_of', to_id: 14 });
  }
  return out;
}

export function benchOf(n: number): BenchDetail {
  const pieces = seedsFor(n).map((s, i) => piece(i + 1, s, i, (n - i) * 7));
  // A pin, and a box (a resize pins too), where the 11 and 32 benches have the pieces for them.
  if (n >= 8) pieces[7]!.placement = { ...pieces[7]!.placement, pin: { x: -820, y: 330 } };
  if (n >= 10) pieces[9]!.placement = { ...pieces[9]!.placement, pin: { x: 700, y: -520 }, box: { w: 260, h: 150 } };
  return {
    bench: { id: 1, title: 'Balcony watering', opened_at: new Date(Date.now() - 86_400_000).toISOString(), closed_at: null, work: null,
      piece_count: pieces.length, last_changed_at: new Date().toISOString(), thread: 'bench-1' },
    pieces, recent: [], undo_next: null, shelf: [], links: linksFor(n),
  } as BenchDetail;
}

function turn(id: number, author: 'person' | 'ashley', text: string, agoMs: number, pieceIds: number[] = []) {
  return { id, author, text, at: new Date(Date.now() - agoMs).toISOString(), follows: false, continued_on: null, attachment: null, runs: [], looks: [],
    working: false, agree: null, voiced: false, receipts: null, agreed: null, piece_ids: pieceIds };
}

export function talkOf(n: number): ChatConversation {
  const last = Math.min(n, 5);
  return {
    thread: 'bench-1', conversation_id: 7, started_at: new Date(Date.now() - 3_600_000).toISOString(),
    turns: [
      turn(1, 'person', 'The bracket cracked at the tab. Can you thicken it?', 3_000_000),
      turn(2, 'ashley', 'Thickened the tab wall to 5 mm and added a fillet; v4 sits beside v3.', 2_900_000, [3, last]),
      turn(3, 'person', 'What does the firmware publish?', 1_200_000),
      turn(4, 'ashley', 'It publishes "dry" on balcony/soil every ten minutes once the reading crosses the line.', 1_100_000, [2]),
      turn(5, 'person', 'And the plan?', 60_000),
      turn(6, 'ashley', 'Five millimetres at the crack, and the print check passes. Want it printed?', 1_500, [last, 1]),
    ],
  } as ChatConversation;
}
