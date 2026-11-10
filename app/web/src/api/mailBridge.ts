// The Proton login routes: one step at a time to Bridge (`POST /api/mail-bridge/login…`), and the accounts Bridge holds.
import { answer, ApiError } from './client';
import type { ProtonAccounts, ProtonLoginRefused, ProtonLoginStep } from './types';

async function step(path: string, body: Record<string, string>): Promise<ProtonLoginStep | ProtonLoginRefused> {
  const response = await fetch(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  if (response.status === 400) return (await response.json()) as ProtonLoginRefused;
  return answer(response, 200, `POST ${path}`);
}

/** Starts a login: the Proton username and password go to Bridge once. A 400 answers why it ended; a 503 is no Bridge running. */
export function startProtonLogin(label: string, username: string, password: string): Promise<ProtonLoginStep | ProtonLoginRefused> {
  return step('/api/mail-bridge/login', { label, username, password });
}

/** The password again after Proton's human check, so Bridge retries the login with the check's details. */
export function sendProtonVerified(label: string, password: string): Promise<ProtonLoginStep | ProtonLoginRefused> {
  return step('/api/mail-bridge/login/verified', { label, password });
}

export function sendProtonCode(label: string, code: string): Promise<ProtonLoginStep | ProtonLoginRefused> {
  return step('/api/mail-bridge/login/two-factor', { label, code });
}

export function sendProtonMailboxPassword(label: string, password: string): Promise<ProtonLoginStep | ProtonLoginRefused> {
  return step('/api/mail-bridge/login/mailbox-password', { label, password });
}

/** The Proton accounts of the connections the person can see, with their state and sync. */
export async function getProtonAccounts(): Promise<ProtonAccounts> {
  const response = await fetch('/api/mail-bridge/accounts');
  if (response.status !== 200) throw new ApiError(response.status, 'GET /api/mail-bridge/accounts');
  return (await response.json()) as ProtonAccounts;
}
