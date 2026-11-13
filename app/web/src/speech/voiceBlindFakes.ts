// Stand-ins for the blind voice tests: the browser's audio (an HTMLAudioElement and an AudioContext that record what was
// asked of them), a fetch that answers a status per turn, and a bundle of voice.ts and talk.ts built the way the client
// is, so each test loads a module of its own. Every name the builder may choose differently is touched in this file.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { mock } from 'node:test';
import { build } from 'esbuild';
import type * as Voice from './voice.ts';
import type { talk as Talk } from './talk.ts';

export type Kind = 'desktop' | 'android' | 'ios';
export interface VoiceTurn { id: number; author: 'person' | 'ashley'; follows: boolean; voiced: boolean }
export interface Loaded { voice: typeof Voice; talk: typeof Talk }

export class World {
  log: string[] = [];
  played: number[] = [];
  fetched: number[] = [];
  audios: FakeAudio[] = [];
  contexts: FakeContext[] = [];
  status = new Map<number, number>();
  rejectPlay: Error | null = null;
  limits = { max_ms: 30000, voice_s: 120 };
  problems: unknown[] = [];
  pauses = 0;
}

let world = new World();
const here = fileURLToPath(new URL('.', import.meta.url));
const idOf = (src: string): number => Number(/(?:turns\/|blob:fake\/)(\d+)/.exec(src)?.[1] ?? -1);
const tagged = new WeakMap<Blob, number>();

export class FakeAudio extends EventTarget {
  src = '';
  paused = true;
  currentTime = 0;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() { super(); world.audios.push(this); }
  async play(): Promise<void> {
    const id = idOf(this.src);
    if (world.rejectPlay) {
      const error = world.rejectPlay;
      world.rejectPlay = null;
      world.log.push(`play.rejected:${id}`);
      throw error;
    }
    if (id >= 0 && !this.src.startsWith('blob:') && (world.status.get(id) ?? 200) !== 200) {
      throw new DOMException('no supported source', 'NotSupportedError');
    }
    if (this.src.startsWith('data:')) {
      world.log.push('audio.silent');
      return;
    }
    this.paused = false;
    world.log.push(`audio.play:${id}`);
    if (id >= 0) world.played.push(id);
  }
  pause(): void { this.paused = true; world.pauses++; world.log.push('audio.pause'); }
  load(): void {}
  removeAttribute(): void { this.src = ''; }
  finish(): void {
    this.paused = true;
    this.onended?.();
    this.dispatchEvent(new Event('ended'));
  }
}

class FakeSource {
  buffer: unknown = null;
  onended: (() => void) | null = null;
  connect(): void {}
  start(): void { world.log.push('ctx.silent'); }
  stop(): void {}
}

export class FakeContext {
  state = 'suspended';
  destination = {};
  currentTime = 0;
  constructor() { world.contexts.push(this); }
  async resume(): Promise<void> { world.log.push('ctx.resume'); this.state = 'running'; }
  async close(): Promise<void> {}
  createBuffer(): unknown { return { duration: 0, length: 1 }; }
  createBufferSource(): FakeSource { return new FakeSource(); }
  async decodeAudioData(): Promise<unknown> { return {}; }
}

async function fakeFetch(input: unknown): Promise<unknown> {
  const id = idOf(String(input));
  world.fetched.push(id);
  const status = world.status.get(id) ?? 200;
  const blob = new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/mpeg' });
  tagged.set(blob, id);
  return {
    ok: status === 200, status, headers: new Headers({ 'content-type': 'audio/mpeg' }),
    blob: async () => blob, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer, json: async () => ({}),
  };
}

const agents: Record<Kind, string> = {
  desktop: 'Mozilla/5.0 (X11; Linux x86_64) Chrome/130',
  android: 'Mozilla/5.0 (Linux; Android 15; Pixel 9) Chrome/130 Mobile',
  ios: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/605.1.15',
};

function put(name: string, value: unknown): void {
  Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
}

/** A fresh browser: the audio fakes, `fetch`, fake timers, and a collector of unhandled rejections. */
export function install(kind: Kind = 'desktop'): World {
  world = new World();
  mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  put('window', globalThis);
  put('navigator', { userAgent: agents[kind] });
  put('Audio', FakeAudio);
  put('HTMLAudioElement', FakeAudio);
  put('AudioContext', FakeContext);
  put('webkitAudioContext', FakeContext);
  put('fetch', fakeFetch);
  put('document', {
    createElement: (tag: string) => (tag === 'audio' ? new FakeAudio() : { style: {}, setAttribute() {} }),
    addEventListener() {}, removeEventListener() {}, visibilityState: 'visible', body: { appendChild() {} },
  });
  URL.createObjectURL = (blob: Blob | MediaSource) => `blob:fake/${tagged.get(blob as Blob) ?? -1}`;
  URL.revokeObjectURL = () => {};
  const guard = (reason: unknown) => world.problems.push(reason);
  process.on('unhandledRejection', guard);
  const error = console.error;
  console.error = (...args: unknown[]) => { world.problems.push(args); };
  world.log.push('installed');
  cleanups.push(() => { process.off('unhandledRejection', guard); console.error = error; mock.timers.reset(); });
  return world;
}

const cleanups: Array<() => void> = [];
export function uninstall(): void { while (cleanups.length) cleanups.pop()!(); }

/** Let every promise the code started settle; fake timers do not move. */
export async function settle(): Promise<void> {
  for (let i = 0; i < 8; i++) await new Promise<void>((resolve) => setImmediate(resolve));
}

export const tick = (ms: number): void => mock.timers.tick(ms);

const clientStub = (names: string[]): string => names.map((name) => {
  if (name === 'ApiError') return 'export class ApiError extends Error { constructor(status) { super("api"); this.status = status; } }';
  if (/limits/i.test(name)) return `export const ${name} = async () => globalThis.__voiceLimits;`;
  if (/url/i.test(name)) return `export const ${name} = (id) => "/api/chat/turns/" + id + "/voice";`;
  return `export const ${name} = () => undefined;`;
}).join('\n');

const recordStub = `export class MicRefused extends Error { constructor(why) { super(why); this.why = why; } }
export const record = async () => { globalThis.__voiceLog.push("mic.open"); return { stop: async () => new Blob(), cancel: () => {} }; };`;

function importedFrom(module: 'client' | 'speech'): string[] {
  const names = new Set<string>();
  const from = new RegExp(`import\\s*(?:type\\s*)?\\{([^}]*)\\}\\s*from\\s*'\\.\\./api/${module}'`, 'g');
  for (const file of ['voice.ts', 'talk.ts']) {
    const source = readFileSync(`${here}${file}`, 'utf8');
    for (const match of source.matchAll(from)) {
      for (const part of match[1]!.split(',')) {
        const name = part.trim().replace(/^type\s+/, '').split(/\s+as\s+/)[0]!;
        if (name && !/^type\s/.test(part.trim())) names.add(name);
      }
    }
  }
  return [...names];
}

const bundle = (async () => {
  const stubs: Record<string, string> = {
    '../api/client': clientStub(importedFrom('client')), '../api/speech': clientStub(importedFrom('speech')), './record': recordStub,
  };
  const built = await build({
    stdin: { contents: "export * as voice from './voice.ts'; export { talk } from './talk.ts';", resolveDir: here,
             loader: 'ts' },
    bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent',
    plugins: [{ name: 'stubs', setup(b) {
      b.onResolve({ filter: /.*/ }, (args) => (args.path in stubs ? { path: args.path, namespace: 'stub' } : undefined));
      b.onLoad({ filter: /.*/, namespace: 'stub' }, (args) => ({ contents: stubs[args.path]!, loader: 'js' }));
    } }],
  });
  return built.outputFiles[0]!.text;
})();

let loads = 0;
/** voice.ts and talk.ts bundled and loaded as a module of their own, so no state is shared with another test. */
export async function load(): Promise<Loaded> {
  const code = `${await bundle}\n// ${++loads}`;
  put('__voiceLimits', world.limits);
  put('__voiceLog', world.log);
  return (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)) as Loaded;
}

export const person = (id: number): VoiceTurn => ({ id, author: 'person', follows: false, voiced: false });
export const hers = (id: number, voiced = true, follows = false): VoiceTurn => ({ id, author: 'ashley', follows, voiced });

/** Hands the room's voice URL to voice.ts, however it takes it. The one place to rewire when the owner is known. */
export function bind(loaded: Loaded, kind: 'chat' | 'kiosk' = 'chat'): void {
  const take = loaded.voice as unknown as Record<string, unknown>;
  const url = (id: number) => `/api/${kind}/turns/${id}/voice`;
  for (const name of ['setVoiceUrl', 'useVoiceUrl', 'configureVoice']) {
    if (typeof take[name] === 'function') (take[name] as (u: (id: number) => string) => void)(url);
  }
}

/** The tap on a turn's play control. The one place to rewire when the control's entry point is known. */
export function tapPlay(loaded: Loaded, id: number): void {
  const take = loaded.voice as unknown as Record<string, unknown>;
  const name = ['playVoice', 'playTurn', 'tapPlay'].find((n) => typeof take[n] === 'function');
  if (!name) throw new Error('voice.ts exports no function for the play control (see gaps.txt)');
  (take[name] as (turn: number) => void)(id);
}

export const playing = (loaded: Loaded): unknown => loaded.voice.state.value;
