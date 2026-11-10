// The connections as the connections room holds them: the kinds the server offers, the household's and the signed-in
// person's own connections as last read, whether they could be read, and adding, replacing, renaming and removing
// each connection, which is addressed by its id.
// Every change goes through here. The key or token a person types is sent once and never kept: the form clears it
// whatever the answer.
import { signal } from '@preact/signals';
import { ApiError } from '../../api/client';
import {
  addConnection, disconnectConnection, getConnections, moveConnection, relabelConnection, replaceConnection, shareResource,
} from '../../api/connections';
import type { ConnectionKindInfo, ConnectionRefused, HouseholdConnection } from '../../api/types';
import { movedRefusal } from './moved';

/** A kind's `name`, as the server registers it. */
export type ConnectionKind = string;
/** Who holds a connection: the household, or the signed-in person alone. */
export type Holder = ConnectionKindInfo['holders'][number];
/** `off`: connections are not set up here (the server holds no key to seal them). */
export type ConnectionsLoad = 'loading' | 'ready' | 'off' | 'failed';
export type ConnectionsSaid =
  | ConnectionRefused['reason']
  | 'connected'
  | 'not_set_up'
  | 'removed'
  | 'renamed'
  | 'handed_over'
  | 'taken_back'
  | 'shared'
  | 'kept'
  | 'not_yours'
  | 'move_label_taken'
  | 'move_too_many'
  | 'remove_failed'
  | 'label_taken'
  | 'too_many'
  | 'failed';

export const kinds = signal<ConnectionKindInfo[]>([]);
/** Every connection the signed-in person can see, in the server's order: by kind, then label. */
export const held = signal<HouseholdConnection[]>([]);
export const connectionsState = signal<ConnectionsLoad>('loading');
/** The kind being checked against its service now, if any. */
export const connecting = signal<ConnectionKind | null>(null);
/** What came of the last change, and to which kind. */
/** `detail` is the kind's own words for a refusal. */
export const connectionsSaid = signal<{ kind: ConnectionKind; said: ConnectionsSaid; detail?: string } | null>(null);

/** The connections of `kind` the person can see. */
export function ofKind(kind: ConnectionKind): HouseholdConnection[] {
  return held.value.filter((c) => c.kind === kind);
}

/** Who a connection of `info` is held by when its person does not say: themselves where the kind allows it. */
export function defaultHolder(info: ConnectionKindInfo): Holder {
  return info.holders.includes('person') ? 'person' : 'household';
}

/** Whether another connection of `info` may be added: its owner holds fewer than the kind's `most`. */
export function canAdd(info: ConnectionKindInfo): boolean {
  return ofKind(info.name).length < info.most;
}

function keep(c: HouseholdConnection): void {
  held.value = held.value.some((h) => h.id === c.id) ? held.value.map((h) => (h.id === c.id ? c : h)) : [...held.value, c];
}

export async function loadConnections(): Promise<void> {
  connectionsState.value = 'loading';
  try {
    const answer = await getConnections();
    kinds.value = answer.offered;
    held.value = answer.connections;
    connectionsState.value = answer.can_connect ? 'ready' : 'off';
  } catch {
    connectionsState.value = 'failed';
  }
}

function secretOf(kind: ConnectionKindInfo, baseUrl: string, secret: string) {
  const base_url = kind.takes_address ? baseUrl : undefined;
  return kind.secret_field === 'api_key' ? { base_url: baseUrl, api_key: secret } : { base_url, token: secret };
}

function refusedBy(error: unknown): ConnectionsSaid {
  if (!(error instanceof ApiError)) return 'failed';
  return error.code === 'too_many' || error.code === 'label_taken' ? error.code : 'failed';
}

/** Adds a connection of `info` under `label`, or with `replacing` gives that one a new address and key or token. True
 * when it was stored; the caller clears the key or token either way. */
export async function connect(info: ConnectionKindInfo, label: string, baseUrl: string, secret: string, replacing?: number): Promise<boolean> {
  const kind = info.name;
  connecting.value = kind;
  connectionsSaid.value = null;
  try {
    const body = secretOf(info, baseUrl, secret);
    const got = replacing === undefined ? await addConnection({ ...body, kind, label }) : await replaceConnection(replacing, body);
    if ('reason' in got) {
      connectionsSaid.value = { kind, said: got.reason, detail: got.detail };
      return false;
    }
    keep(got);
    connectionsSaid.value = { kind, said: 'connected' };
    return true;
  } catch (error) {
    connectionsSaid.value = { kind, said: refusedBy(error) };
    return false;
  } finally {
    connecting.value = null;
  }
}

/** True when the connection now has `label`. */
export async function rename(c: HouseholdConnection, label: string): Promise<boolean> {
  connectionsSaid.value = null;
  try {
    keep(await relabelConnection(c.id, label));
    connectionsSaid.value = { kind: c.kind, said: 'renamed' };
    return true;
  } catch (error) {
    connectionsSaid.value = { kind: c.kind, said: refusedBy(error) };
    return false;
  }
}

/** Hands `c` to the household (every resource of it becomes shared) or takes it back (every resource kept again). True when it moved. */
export async function move(c: HouseholdConnection, holder: Holder): Promise<boolean> {
  connectionsSaid.value = null;
  try {
    keep(await moveConnection(c.id, holder));
    connectionsSaid.value = { kind: c.kind, said: holder === 'household' ? 'handed_over' : 'taken_back' };
    return true;
  } catch (error) {
    connectionsSaid.value = { kind: c.kind, said: error instanceof ApiError ? movedRefusal(error.code) : 'failed' };
    return false;
  }
}

/** Shares or keeps one resource of `c`, and says which. */
export async function share(c: HouseholdConnection, ref: string, shared: boolean): Promise<void> {
  connectionsSaid.value = null;
  try {
    const changed = await shareResource(c.id, ref, shared);
    keep({ ...c, resources: c.resources.map((r) => (r.ref === ref ? changed : r)) });
    connectionsSaid.value = { kind: c.kind, said: shared ? 'shared' : 'kept' };
  } catch {
    connectionsSaid.value = { kind: c.kind, said: 'failed' };
  }
}

export async function disconnect(c: HouseholdConnection): Promise<void> {
  const gone = () => {
    held.value = held.value.filter((h) => h.id !== c.id);
    connectionsSaid.value = { kind: c.kind, said: 'removed' };
  };
  try {
    await disconnectConnection(c.id);
    gone();
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) gone();
    else connectionsSaid.value = { kind: c.kind, said: 'remove_failed' };
  }
}
