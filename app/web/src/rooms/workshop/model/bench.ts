// The bench open on this screen: as the server last answered it, read back whenever the live feed says it changed (her
// change, another tab's, this page's own), and every change to it a command sent from here, one at a time. Each read
// also says which commands landed since the one before (`stamps`), so the grid can show each change by piece id.
import { signal } from '@preact/signals';
import { ApiError, applyCommand, getBench, runPiece } from '../../../api/client';
import type { BenchDetail, BenchPiece, CommandRequest, RefusalReason } from '../../../api/types';
import { liveUp, onBenchChanged, onResync } from '../../../session/live';
import { roomReached } from '../../../shell/her/state';
import { unreachable } from './benches';
import { stampsOf, type Stamp } from './log';

/** `missing`: no bench of this person's has the id (404). */
export type BenchLoad = 'loading' | 'ready' | 'missing' | 'unreachable' | 'failed';
/** How a command ended: accepted, refused with the server's reason, the bench closed (410), or not sent through. */
export type Outcome = { ok: true; piece: number | null } | { ok: false; why: RefusalReason | 'closed' | 'unreachable' | 'failed' | UploadWhy };
/** Why a file was not taken that is not a bench refusal: over the size limit, not a type a bench takes, or empty. */
export type UploadWhy = 'too_large' | 'unsupported' | 'empty';

export const detail = signal<BenchDetail | null>(null);
export const benchState = signal<BenchLoad>('loading');
/** The commands the latest read found since the read before it; replaced by each read. */
export const stamps = signal<readonly Stamp[]>([]);
/** The last command's outcome worth a line on screen; cleared by the next command. */
export const notice = signal<Outcome | null>(null);
/** The pieces this page has asked to run and not yet heard back about, by id. */
export const running = signal<ReadonlySet<number>>(new Set());

/** While the live feed is down, the bench is read back this often. */
const FALLBACK_MS = 10000;
/** A file link is read again this long before it ends, and no sooner than `LINK_MIN_MS` from now. */
const LINK_MARGIN_MS = 30000;
const LINK_MIN_MS = 5000;

let openId: number | null = null;
let reads = 0;
let queue: Promise<unknown> = Promise.resolve();
let fallbackTimer: ReturnType<typeof setTimeout> | undefined;
let linkTimer: ReturnType<typeof setTimeout> | undefined;
let unsubscribe: (() => void)[] = [];

let newest: Promise<void> = Promise.resolve();

/** Reads the bench back. A read a later one overtook waits for that one, so whoever awaits a read sees the bench at
 * least as new as when they asked. */
function readBack(id: number): Promise<void> {
  newest = read(id, ++reads);
  return newest;
}

async function read(id: number, mine: number): Promise<void> {
  const got = await getBench(id);
  if (id !== openId) return;
  if (mine !== reads) return newest;
  stamps.value = stampsOf(detail.value, got);
  detail.value = got;
  benchState.value = 'ready';
  readBeforeLinksEnd(id, got);
}

/** A piece's file link stops working at `expires_at`; the bench is read again a little before the first does, so a
 * page left open keeps its images. */
function readBeforeLinksEnd(id: number, got: BenchDetail): void {
  clearTimeout(linkTimer);
  const ends = [...got.pieces, ...got.shelf].flatMap((p) => (p.file?.expires_at ? [p.file.expires_at] : []));
  if (!ends.length) return;
  const wait = Math.max(LINK_MIN_MS, Math.min(...ends) * 1000 - Date.now() - LINK_MARGIN_MS);
  linkTimer = setTimeout(() => id === openId && void refresh(), wait);
}

/** Reads the open bench back without showing a load; a failure keeps what is shown. */
export async function refresh(): Promise<void> {
  if (openId === null) return;
  try {
    await readBack(openId);
    roomReached(true);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) benchState.value = 'missing';
    else roomReached(!unreachable(error));
  }
}

/** The first read of a bench, and "Try again". */
export async function loadBench(): Promise<void> {
  const id = openId;
  if (id === null) return;
  if (detail.value?.bench.id !== id) detail.value = null;
  benchState.value = 'loading';
  try {
    await readBack(id);
    roomReached(true);
  } catch (error) {
    if (id !== openId) return;
    if (error instanceof ApiError && error.status === 404) benchState.value = 'missing';
    else benchState.value = unreachable(error) ? 'unreachable' : 'failed';
    roomReached(benchState.value !== 'unreachable');
  }
}

function outcomeOf(error: unknown): Outcome {
  if (error instanceof ApiError && error.status === 410) return { ok: false, why: 'closed' };
  return { ok: false, why: unreachable(error) ? 'unreachable' : 'failed' };
}

async function sent(call: () => Promise<{ piece_id: number | null } | { reason: RefusalReason }>): Promise<Outcome> {
  try {
    const got = await call();
    return 'reason' in got ? { ok: false, why: got.reason } : { ok: true, piece: got.piece_id };
  } catch (error) {
    return outcomeOf(error);
  }
}

async function send(id: number, command: CommandRequest | Run): Promise<Outcome> {
  const outcome = await sent(() => 'language' in command
    ? runPiece(id, { piece_id: command.piece.id, base_version: command.piece.piece_version, run_language: command.language })
    : applyCommand(id, command));
  if (id !== openId) return outcome;
  notice.value = outcome.ok ? null : outcome;
  if (!(!outcome.ok && outcome.why === 'unreachable')) await refresh();
  return outcome;
}

interface Run {
  piece: BenchPiece;
  language: string;
}

function toggle(piece: number, on: boolean): void {
  const next = new Set(running.value);
  if (on) next.add(piece);
  else next.delete(piece);
  running.value = next;
}

/** Runs `piece` as this page shows it, in `language`, after any command still on its way; the bench is read back once
 * the run has ended, its result on the piece. */
export async function run(piece: BenchPiece, language: string): Promise<Outcome> {
  toggle(piece.id, true);
  try {
    return await enqueue({ piece, language });
  } finally {
    toggle(piece.id, false);
  }
}

/** Sends one command to the open bench after any still on their way, then reads the bench back. */
export function apply(command: CommandRequest): Promise<Outcome> {
  return enqueue(command);
}

function enqueue(command: CommandRequest | Run): Promise<Outcome> {
  const id = openId;
  if (id === null) return Promise.resolve({ ok: false, why: 'failed' });
  notice.value = null;
  const done = queue.then(() => send(id, command));
  queue = done.catch(() => undefined);
  return done;
}

function fallback(id: number): void {
  if (openId !== id) return;
  if (!liveUp.value && !document.hidden) void refresh();
  fallbackTimer = setTimeout(() => fallback(id), FALLBACK_MS);
}

/** Bench `id` is shown: read it, then read it back whenever it changes, until it is left. */
export function enterBench(id: number): void {
  if (openId === id) return;
  leaveBench();
  openId = id;
  notice.value = null;
  stamps.value = [];
  unsubscribe = [onBenchChanged((bench) => bench === id && void refresh()), onResync(() => void refresh())];
  fallbackTimer = setTimeout(() => fallback(id), FALLBACK_MS);
  void loadBench();
}

/** The bench is no longer shown: stop reading it back. What it showed stays until another bench is read. */
export function leaveBench(): void {
  openId = null;
  reads++;
  clearTimeout(fallbackTimer);
  clearTimeout(linkTimer);
  unsubscribe.forEach((u) => u());
  unsubscribe = [];
}
