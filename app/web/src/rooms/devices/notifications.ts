// Notifications on this device: whether this browser is pushed to for the person signed in, and turning it on or off.
// Every change goes through here. The browser's own subscription (service worker /sw.js) and the server's record of
// whose it is are both consulted, so "on" means she will push here for this person.
import { signal } from '@preact/signals';
import { ApiError, findPush, getPushKey, subscribePush, unsubscribePush } from '../../api/client';

/** `unsupported`: this browser has no web push (on iPhone, until the app is on the Home Screen); `unavailable`: push is
 * not set up on the server (503); `blocked`: the browser's notification permission is denied; `failed`: anything else
 * stopped the read. */
export type Push = 'loading' | 'unsupported' | 'unavailable' | 'blocked' | 'off' | 'on' | 'failed';

export const push = signal<Push>('loading');
/** True while a turn on or off is in flight. */
export const pushBusy = signal(false);
/** What the last change came to; null when there is nothing to say. */
export const pushSaid = signal<'on' | 'off' | 'denied' | 'failed' | 'unreachable' | null>(null);

let key = '';

function supported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

async function registration(): Promise<ServiceWorkerRegistration> {
  await navigator.serviceWorker.register('/sw.js', { scope: '/' });
  return navigator.serviceWorker.ready;
}

/** A 503, or no answer at all (fetch rejects with a TypeError); a browser refusing to subscribe is neither. */
function unreachable(error: unknown): boolean {
  return error instanceof ApiError ? error.status === 503 : error instanceof TypeError;
}

export async function loadPush(): Promise<void> {
  push.value = 'loading';
  if (!supported()) {
    push.value = 'unsupported';
    return;
  }
  try {
    key = (await getPushKey()).public_key;
    if (Notification.permission === 'denied') {
      push.value = 'blocked';
      return;
    }
    const mine = await (await registration()).pushManager.getSubscription();
    push.value = mine && (await findPush(mine.endpoint)).this_browser ? 'on' : 'off';
  } catch (error) {
    push.value = error instanceof ApiError && error.status === 503 ? 'unavailable' : 'failed';
  }
}

function applicationServerKey(base64url: string): Uint8Array<ArrayBuffer> {
  const raw = atob(base64url.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export async function turnOn(): Promise<void> {
  pushBusy.value = true;
  pushSaid.value = null;
  try {
    if ((await Notification.requestPermission()) !== 'granted') {
      const blocked = Notification.permission === 'denied';
      push.value = blocked ? 'blocked' : 'off';
      pushSaid.value = blocked ? null : 'denied';
      return;
    }
    const manager = (await registration()).pushManager;
    const subscription = (await manager.getSubscription())
      ?? (await manager.subscribe({ userVisibleOnly: true, applicationServerKey: applicationServerKey(key) }));
    await subscribePush(subscription.toJSON());
    push.value = 'on';
    pushSaid.value = 'on';
  } catch (error) {
    pushSaid.value = unreachable(error) ? 'unreachable' : 'failed';
  } finally {
    pushBusy.value = false;
  }
}

export async function turnOff(): Promise<void> {
  pushBusy.value = true;
  pushSaid.value = null;
  try {
    const subscription = await (await registration()).pushManager.getSubscription();
    if (subscription) {
      await unsubscribePush(subscription.endpoint);
      await subscription.unsubscribe();
    }
    push.value = 'off';
    pushSaid.value = 'off';
  } catch (error) {
    pushSaid.value = unreachable(error) ? 'unreachable' : 'failed';
  } finally {
    pushBusy.value = false;
  }
}
