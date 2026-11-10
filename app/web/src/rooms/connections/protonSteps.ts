// What a Proton login asks for next, in words, and what Bridge says of an account: the parts of the room that are plain
// functions of what the server answered.
import type { ProtonAccount, ProtonLoginRefused, ProtonLoginStep } from '../../api/types';

export type ProtonAsk = 'credentials' | 'two_factor' | 'mailbox_password' | 'human_verification';
export type ProtonSaid = ProtonLoginRefused['reason'] | 'unavailable' | 'failed';

export const SAID: Record<ProtonSaid, string> = {
  credentials: 'Proton did not accept that username and password.',
  code: 'Proton did not accept that code. Start again.',
  mailbox_password: 'Proton did not accept that mailbox password. Start again.',
  label_taken: 'You already have a Proton account under that name.',
  too_many: 'You already have as many Proton accounts as can be connected.',
  paid_plan: 'Bridge needs a paid Proton plan.',
  connection: 'Bridge could not reach Proton. Try again.',
  aborted: 'Bridge ended that login, after too many tries or because it lost track of it. Start again.',
  verification: "Proton's check did not pass. Try again.",
  security_key: "This account's two-factor is a security key only. Bridge needs an authenticator-app code; add one in Proton's settings.",
  other: 'Bridge could not log that account in.',
  unavailable: 'Proton Mail Bridge is not running right now. Try again shortly.',
  failed: 'That did not go through. Try again.',
};

/** What the login does with an answer: asks for the next step, is done, or is over with something to say. */
export type ProtonNext =
  | { to: 'ask'; ask: 'two_factor' | 'mailbox_password' }
  | { to: 'verify'; url: string }
  | { to: 'done' }
  | { to: 'said'; said: ProtonSaid };

/** A refusal ends the login at its first step; its reason is said, never taken for a step to ask. */
export function nextOf(got: ProtonLoginStep | ProtonLoginRefused): ProtonNext {
  if ('reason' in got) return { to: 'said', said: got.reason };
  if (got.step === 'human_verification') {
    return got.verification_url ? { to: 'verify', url: got.verification_url } : { to: 'said', said: 'failed' };
  }
  if (got.step === 'two_factor' || got.step === 'mailbox_password') return { to: 'ask', ask: got.step };
  return { to: 'done' };
}

/** What goes to Bridge for what was typed at `ask`: a password exactly as typed, a code without the spaces around it. */
export function sentOf(ask: ProtonAsk, typed: string): string {
  return ask === 'two_factor' ? typed.trim() : typed;
}

/** What Bridge says of an account in a few words; null when nothing was read for it. */
export function stateOf(account: ProtonAccount | undefined): string | null {
  if (!account) return null;
  if (account.state === 'signed_out') return 'Signed out; log in again';
  if (account.state === 'locked') return 'Locked';
  if (!account.syncing) return 'Up to date';
  return account.sync_progress === null ? 'Copying mail' : `Copying mail, ${Math.round(account.sync_progress * 100)}%`;
}
