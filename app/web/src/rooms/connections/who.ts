// Who a resource of a connection (a mailbox) is for: its owner alone, or the household.
export type Who = 'me' | 'household';

export function whoOf(shared: boolean): Who {
  return shared ? 'household' : 'me';
}

/** The `shared` value to send when `pick` is chosen for a resource now `shared`; null when it is already so. */
export function sharedFor(shared: boolean, pick: Who): boolean | null {
  const wanted = pick === 'household';
  return wanted === shared ? null : wanted;
}
