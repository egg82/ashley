// Proton accounts in the connections room: where a login stands (a name, then the password, the two-factor code and the
// mailbox password as Bridge asks for them), and what Bridge says of each account once connected (its state, whether it is
// still syncing). What a person types is sent once and never kept: the form clears it whatever the answer.
import { signal } from '@preact/signals';
import { ApiError } from '../../api/client';
import {
  getProtonAccounts, sendProtonCode, sendProtonMailboxPassword, sendProtonVerified, startProtonLogin,
} from '../../api/mailBridge';
import type { ConnectionKindInfo, ProtonAccount, ProtonLoginRefused, ProtonLoginStep } from '../../api/types';
import { nextOf, type ProtonAsk, type ProtonSaid } from './protonSteps';
import { loadConnections } from './connections';

/** What the login asks the person for next. */
export const asking = signal<ProtonAsk>('credentials');
export const loginSaid = signal<ProtonSaid | null>(null);
/** Proton's human-check page while the login waits on it, else null. */
export const verifyUrl = signal<string | null>(null);
export const sending = signal(false);
/** Bridge's accounts by connection id, as last read; empty until read. */
export const accounts = signal<Map<number, ProtonAccount>>(new Map());

/** Back to the first step, with nothing said. */
export function resetLogin(): void {
  asking.value = 'credentials';
  loginSaid.value = null;
  verifyUrl.value = null;
  sending.value = false;
}

async function relay(send: () => Promise<ProtonLoginStep | ProtonLoginRefused>): Promise<boolean> {
  sending.value = true;
  loginSaid.value = null;
  try {
    const next = nextOf(await send());
    if (next.to === 'done') {
      await loadConnections();
      await loadProtonAccounts();
      return true;
    }
    if (next.to === 'ask') asking.value = next.ask;
    else if (next.to === 'verify') {
      verifyUrl.value = next.url;
      asking.value = 'human_verification';
    } else {
      loginSaid.value = next.said;
      verifyUrl.value = null;
      asking.value = 'credentials';
    }
    return false;
  } catch (error) {
    loginSaid.value = error instanceof ApiError && error.status === 503 ? 'unavailable' : 'failed';
    return false;
  } finally {
    sending.value = false;
  }
}

/** True when the account is connected and stored. */
export function logIn(label: string, username: string, password: string): Promise<boolean> {
  return relay(() => startProtonLogin(label, username, password));
}

/** The password again, once the person has passed Proton's check in their own browser. */
export function sendVerified(label: string, password: string): Promise<boolean> {
  return relay(() => sendProtonVerified(label, password));
}

export function sendCode(label: string, code: string): Promise<boolean> {
  return relay(() => sendProtonCode(label, code));
}

export function sendMailboxPassword(label: string, password: string): Promise<boolean> {
  return relay(() => sendProtonMailboxPassword(label, password));
}

export async function loadProtonAccounts(): Promise<void> {
  try {
    accounts.value = new Map((await getProtonAccounts()).proton_accounts.map((a) => [a.connection_id, a]));
  } catch {
    accounts.value = new Map();
  }
}

/** Whether `kind` is connected by logging in to Bridge. */
export function isBridge(kind: ConnectionKindInfo): boolean {
  return kind.connect === 'bridge';
}
