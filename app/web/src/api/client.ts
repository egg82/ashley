// The only place the app calls the API. Each function's type is read from the generated schema, so a route that
// changes in `openapi.json` is a compile error here.
import type { paths } from './schema';
import type {
  BenchDetail,
  LookPage,
  BenchRequest,
  BenchSummary,
  CommandApplied,
  CommandRefused,
  CommandRequest,
  ChatReply,
  BenchMessage,
  ChatMessage,
  CorrectionRequest,
  KioskDevice,
  KioskMessage,
  KioskGlance,
  LexiconRefused,
  LexiconWord,
  LexiconWords,
  MoveRequest,
  RememberRequest,
  RememberResponse,
  RunApplied,
  RunRequest,
} from './types';

type Ok<P extends keyof paths> = paths[P] extends {
  get: { responses: { 200: { content: { 'application/json': infer B } } } };
}
  ? B
  : never;

type Corrected = paths['/api/memory/facts/{fact_id}/corrections']['post']['responses'][201]['content']['application/json'];
type Moved = paths['/api/memory/facts/{fact_id}/moves']['post']['responses'][201]['content']['application/json'];
type Forgotten = paths['/api/memory/facts/{fact_id}']['delete']['responses'][200]['content']['application/json'];
type Cancelled = paths['/api/reminders/{reminder_id}']['delete']['responses'][200]['content']['application/json'];
type ControlDone = paths['/api/kiosk/controls/{name}']['post']['responses'][200]['content']['application/json'];
type LinkStarted = paths['/api/accounts/discord/link']['post']['responses'][201]['content']['application/json'];
type PushState = paths['/api/push/subscriptions']['post']['responses'][201]['content']['application/json'];

/** A response outside a route's success code. `status` is what callers branch on; no body text reaches the page. */
export class ApiError extends Error {
  constructor(readonly status: number, route: string, readonly code?: string) {
    super(`${route}: ${status}`);
  }
}

export async function answer<B>(response: Response, ok: number, route: string): Promise<B> {
  if (response.status !== ok) throw new ApiError(response.status, route);
  return (await response.json()) as B;
}

/** Every current fact that concerns the signed-in person, newest first. */
export async function getFacts(): Promise<Ok<'/api/memory/facts'>> {
  return answer(await fetch('/api/memory/facts'), 200, 'GET /api/memory/facts');
}

/** Replaces fact `id` with `body.text`; answers the new fact, whose `replaced` is the old one. Same-origin JSON. */
export async function correctFact(id: number, body: CorrectionRequest): Promise<Corrected> {
  const response = await fetch(`/api/memory/facts/${id}/corrections`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return answer(response, 201, 'POST /api/memory/facts/{id}/corrections');
}

/** Makes fact `id` the household's or the signed-in person's; answers the new fact, whose `replaced` is the old one. Same-origin JSON. */
export async function moveFact(id: number, body: MoveRequest): Promise<Moved> {
  const response = await fetch(`/api/memory/facts/${id}/moves`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return answer(response, 201, 'POST /api/memory/facts/{id}/moves');
}

/** Deletes fact `id` and every earlier version it replaced, for good. */
export async function forgetFact(id: number): Promise<Forgotten> {
  return answer(await fetch(`/api/memory/facts/${id}`, { method: 'DELETE' }), 200, 'DELETE /api/memory/facts/{id}');
}

/** The signed-in person's reminders still to fire, for them or set by them, soonest first. */
export async function getReminders(): Promise<Ok<'/api/reminders'>> {
  return answer(await fetch('/api/reminders'), 200, 'GET /api/reminders');
}

/** The signed-in person's open errands and benches, those waiting on them first. */
export async function getWork(): Promise<Ok<'/api/work'>> {
  return answer(await fetch('/api/work'), 200, 'GET /api/work');
}

/** Cancels reminder `id`; a repeating one fires no more. 404 when it is not theirs or already fired. */
export async function cancelReminder(id: number): Promise<Cancelled> {
  return answer(await fetch(`/api/reminders/${id}`, { method: 'DELETE' }), 200, 'DELETE /api/reminders/{id}');
}

/** Asks her to remember one line of a conversation the person took part in; answers what changed. Same-origin JSON. */
export async function rememberTurn(body: RememberRequest): Promise<RememberResponse> {
  const response = await fetch('/api/memory/remembered', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return answer(response, 200, 'POST /api/memory/remembered');
}

/** The signed-in person's accounts elsewhere, and whether linking Discord is set up here. */
export async function getAccounts(): Promise<Ok<'/api/accounts'>> {
  return answer(await fetch('/api/accounts'), 200, 'GET /api/accounts');
}

/** The signed-in person's household's devices. */
export async function getDevices(): Promise<Ok<'/api/devices'>> {
  return answer(await fetch('/api/devices'), 200, 'GET /api/devices');
}

/** The household's pronunciation words and the most it may hold. */
export async function getLexicon(): Promise<LexiconWords> {
  return answer(await fetch('/api/lexicon'), 200, 'GET /api/lexicon');
}

/** Sets how the voice says `real`. A 422 answers why nothing was stored. Same-origin JSON. */
export async function putLexiconWord(real: string, spoken: string): Promise<LexiconWord | LexiconRefused> {
  const response = await fetch(`/api/lexicon/${encodeURIComponent(real)}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ spoken }),
  });
  if (response.status === 422) return (await response.json()) as LexiconRefused;
  return answer(response, 200, 'PUT /api/lexicon/{real}');
}

/** Removes `real` from the household's words; a 404 is one already gone. */
export async function deleteLexiconWord(real: string): Promise<void> {
  const response = await fetch(`/api/lexicon/${encodeURIComponent(real)}`, { method: 'DELETE' });
  if (response.status !== 204) throw new ApiError(response.status, 'DELETE /api/lexicon/{real}');
}

/** What each provider has been used for and cost, and what it says is left. */
export async function getSpend(): Promise<Ok<'/api/spend'>> {
  return answer(await fetch('/api/spend'), 200, 'GET /api/spend');
}

/** Starts linking a Discord account for the person signed in; answers the Discord page to send the browser to. */
export async function startDiscordLink(): Promise<LinkStarted> {
  return answer(await fetch('/api/accounts/discord/link', { method: 'POST' }), 201, 'POST /api/accounts/discord/link');
}

/** Unlinks one of the person's own Discord accounts. */
export async function unlinkAccount(id: number): Promise<void> {
  const response = await fetch(`/api/accounts/${id}`, { method: 'DELETE' });
  if (response.status !== 204) throw new ApiError(response.status, 'DELETE /api/accounts/{id}');
}

/** Sends what the person typed on their own web thread; answers her reply. Same-origin JSON. */
export async function sendChat(body: ChatMessage): Promise<ChatReply> {
  const response = await fetch('/api/chat/messages', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return answer(response, 200, 'POST /api/chat/messages');
}

/** The open conversation on the person's web thread, oldest turn first; empty when none is open. */
export async function getChat(): Promise<Ok<'/api/chat/conversation'>> {
  return answer(await fetch('/api/chat/conversation'), 200, 'GET /api/chat/conversation');
}

/** A page of the conversations the person took part in, newest activity first, after the `before` a page returned. */
export async function getPastPage(limit: number, before: string | null): Promise<Ok<'/api/chat/conversations'>> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (before !== null) query.set('before', before);
  return answer(await fetch(`/api/chat/conversations?${query}`), 200, 'GET /api/chat/conversations');
}

/** A page of the conversations on bench `id`'s thread, closed ones too, newest activity first, after the `before` a page returned. */
export async function getBenchPage(id: number, limit: number, before: string | null): Promise<Ok<'/api/benches/{bench_id}/conversations'>> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (before !== null) query.set('before', before);
  return answer(await fetch(`/api/benches/${id}/conversations?${query}`), 200, 'GET /api/benches/{id}/conversations');
}

/** One earlier conversation of the person's, with its turns oldest first. */
export async function getPast(id: number): Promise<Ok<'/api/chat/conversations/{conversation_id}'>> {
  return answer(await fetch(`/api/chat/conversations/${id}`), 200, 'GET /api/chat/conversations/{id}');
}

/** What a bench allows: the piece kinds, the sizes a piece takes, the most pieces and the longest title. */
export async function getWorkshopKinds(): Promise<Ok<'/api/workshop/kinds'>> {
  return answer(await fetch('/api/workshop/kinds'), 200, 'GET /api/workshop/kinds');
}

/** The signed-in person's open benches, the most recently opened first. */
export async function getBenches(): Promise<Ok<'/api/benches'>> {
  return answer(await fetch('/api/benches'), 200, 'GET /api/benches');
}

/** The signed-in person's closed benches, the most recently closed first. */
export async function getClosedBenches(): Promise<Ok<'/api/benches/closed'>> {
  return answer(await fetch('/api/benches/closed'), 200, 'GET /api/benches/closed');
}

function postJson(path: string, body: unknown): Promise<Response> {
  return fetch(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
}

/** Opens a new bench; answers it. Same-origin JSON. */
export async function openBench(body: BenchRequest): Promise<BenchSummary> {
  return answer(await postJson('/api/benches', body), 200, 'POST /api/benches');
}

/** Bench `id` as a screen shows it, open or closed. */
export async function getBench(id: number): Promise<BenchDetail> {
  return answer(await fetch(`/api/benches/${id}`), 200, 'GET /api/benches/{id}');
}

/** What a browser pod photographs: the bench, or one piece of it, a token's holder may see (`ashley.looks.links`). */
export async function getLook(token: string): Promise<LookPage> {
  return answer(await fetch(`/api/look/${encodeURIComponent(token)}`), 200, 'GET /api/look/{token}');
}

/** Closes bench `id`: it is put away, kept unchanged and listed among the closed benches. */
export async function closeBench(id: number): Promise<BenchSummary> {
  return answer(await fetch(`/api/benches/${id}/close`, { method: 'POST' }), 200, 'POST /api/benches/{id}/close');
}

/** Reopens closed bench `id` as it was closed. */
export async function reopenBench(id: number): Promise<BenchSummary> {
  return answer(await fetch(`/api/benches/${id}/reopen`, { method: 'POST' }), 200, 'POST /api/benches/{id}/reopen');
}

/** One change to bench `id`. A refusal (409) is an answer, not an error: nothing changed, and `reason` says why. */
export async function applyCommand(id: number, body: CommandRequest): Promise<CommandApplied | CommandRefused> {
  const response = await postJson(`/api/benches/${id}/commands`, body);
  if (response.status === 409) return (await response.json()) as CommandRefused;
  return answer(response, 200, 'POST /api/benches/{id}/commands');
}

/** Runs a code piece of bench `id`; answers once the run has ended, or the bench's refusal (409). Same-origin JSON. */
export async function runPiece(id: number, body: RunRequest): Promise<RunApplied | CommandRefused> {
  const response = await postJson(`/api/benches/${id}/runs`, body);
  if (response.status === 409) return (await response.json()) as CommandRefused;
  return answer(response, 200, 'POST /api/benches/{id}/runs');
}

/** Sends what the person typed on bench `id`'s talk; answers her reply. Same-origin JSON. */
export async function sendOnBench(id: number, body: BenchMessage): Promise<ChatReply> {
  return answer(await postJson(`/api/benches/${id}/messages`, body), 200, 'POST /api/benches/{id}/messages');
}

/** The open conversation on bench `id`'s thread, oldest turn first; empty when none is open. */
export async function getBenchConversation(id: number): Promise<Ok<'/api/benches/{bench_id}/conversation'>> {
  return answer(await fetch(`/api/benches/${id}/conversation`), 200, 'GET /api/benches/{id}/conversation');
}

/** The live feed for the signed-in person: Server-Sent Events, one `LiveEvent` per message. `screen` is this page's
 * token (`session/screen.ts`), the name its visibility reports go by. */
export function liveFeed(screen: string): EventSource {
  const path: keyof paths = '/api/live';
  return new EventSource(`${path}?screen=${screen}`);
}

/** The live feed for the paired kiosk, as its device: Server-Sent Events, one `LiveEvent` per message. */
export function kioskLiveFeed(screen: string): EventSource {
  const path: keyof paths = '/api/kiosk/live';
  return new EventSource(`${path}?screen=${screen}`);
}

/** Her VAPID public key, which this browser subscribes with. 503 when push is not set up here. */
export async function getPushKey(): Promise<Ok<'/api/push/key'>> {
  return answer(await fetch('/api/push/key'), 200, 'GET /api/push/key');
}

function pushWrite(method: string, path: string, body: unknown): Promise<Response> {
  return fetch(path, { method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
}

/** Keeps this browser's push subscription for the person signed in, moving it from whoever had it. */
export async function subscribePush(subscription: PushSubscriptionJSON): Promise<PushState> {
  return answer(await pushWrite('POST', '/api/push/subscriptions', subscription), 201, 'POST /api/push/subscriptions');
}

/** Whether the browser at `endpoint` is the signed-in person's, and how many they have. Changes nothing. */
export async function findPush(endpoint: string): Promise<PushState> {
  return answer(await pushWrite('POST', '/api/push/subscriptions/find', { endpoint }), 200,
    'POST /api/push/subscriptions/find');
}

/** Stops pushing to the browser at `endpoint`, when it is the signed-in person's. */
export async function unsubscribePush(endpoint: string): Promise<PushState> {
  return answer(await pushWrite('DELETE', '/api/push/subscriptions', { endpoint }), 200,
    'DELETE /api/push/subscriptions');
}

/** Pairs this browser as the device `token` signs in; the server keeps the token in the kiosk's own cookie. */
export async function pairKiosk(token: string): Promise<KioskDevice> {
  const response = await fetch('/api/kiosk/session', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ token }),
  });
  return answer(response, 200, 'POST /api/kiosk/session');
}

/** The device this browser is paired as; 401 when it is not paired. */
export async function getKioskDevice(): Promise<KioskDevice> {
  return answer(await fetch('/api/kiosk/device'), 200, 'GET /api/kiosk/device');
}

/** The open conversation on the kiosk's thread, oldest turn first; empty when none is open. */
export async function getKioskConversation(): Promise<Ok<'/api/kiosk/conversation'>> {
  return answer(await fetch('/api/kiosk/conversation'), 200, 'GET /api/kiosk/conversation');
}

/** Sends what was typed on the kiosk; answers her reply, which is the answer. Same-origin JSON. */
export async function sendKiosk(body: KioskMessage): Promise<ChatReply> {
  const response = await fetch('/api/kiosk/messages', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return answer(response, 200, 'POST /api/kiosk/messages');
}

export async function getKioskGlance(): Promise<KioskGlance> {
  return answer(await fetch('/api/kiosk/glance'), 200, 'GET /api/kiosk/glance');
}

/** The screen's layout as she has arranged it; `laid_out` false until something changed it. Not counted against the device's rate. */
export async function getKioskLayout(): Promise<unknown> {
  return answer(await fetch('/api/kiosk/layout'), 200, 'GET /api/kiosk/layout');
}

export async function getKioskControls(): Promise<Ok<'/api/kiosk/controls'>> {
  return answer(await fetch('/api/kiosk/controls'), 200, 'GET /api/kiosk/controls');
}

/** Carries out control `name`; whether her tool reported it done. */
export async function runKioskControl(name: string): Promise<boolean> {
  const response = await fetch(`/api/kiosk/controls/${encodeURIComponent(name)}`, { method: 'POST' });
  const done = await answer<ControlDone>(response, 200, 'POST /api/kiosk/controls/{name}');
  return done.done;
}

export async function getHealth(): Promise<Ok<'/api/health'>> {
  const response = await fetch('/api/health');
  if (!response.ok) throw new Error(`GET /api/health: ${response.status}`);
  return (await response.json()) as Ok<'/api/health'>;
}

/** Who this browser is signed in as, or null when it has no live session (401). Any other failure throws. */
export async function getMe(): Promise<Ok<'/api/me'> | null> {
  const response = await fetch('/api/me');
  if (response.status === 401) return null;
  if (!response.ok) throw new Error(`GET /api/me: ${response.status}`);
  return (await response.json()) as Ok<'/api/me'>;
}

/** Ends this browser's session; the server answers 204 whether or not one was live. */
export async function signOut(): Promise<void> {
  const response = await fetch('/api/auth/signout', { method: 'POST' });
  if (response.status !== 204) throw new Error(`POST /api/auth/signout: ${response.status}`);
}

/** Where the sign-in button sends the browser: the provider, then back to `next`, a path on this site. */
export function signinHref(next: string): string {
  return `/api/auth/signin?next=${encodeURIComponent(next)}`;
}
