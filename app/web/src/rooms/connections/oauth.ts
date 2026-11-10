// Connecting a kind through its service's own consent screen: the start that sends this browser away, and where the
// service's callback sent it back, as `/connections?connect=<outcome>`.
import { signal } from '@preact/signals';
import { ApiError } from '../../api/client';
import { startOAuthConnect } from '../../api/connections';
import type { ConnectionKindInfo } from '../../api/types';
import type { ConnectOutcome } from './connectOutcome';
import { connecting, connectionsSaid, type Holder } from './connections';

/** What the last return from a consent screen came to; null when there is nothing to say. */
export const returned = signal<ConnectOutcome | null>(null);

/** Whether a kind is connected through a consent screen. */
export function isOAuth(kind: ConnectionKindInfo): boolean {
  return kind.connect === 'oauth';
}

/** Asks to connect `kind` under `label`, held by `holder`, and sends this browser to the service, which returns it to
 * `/connections?connect=<outcome>`. The kind's name is its provider's. A failure is said as the kind's own. */
export async function connectOAuth(kind: ConnectionKindInfo, label: string, holder: Holder): Promise<void> {
  connecting.value = kind.name;
  connectionsSaid.value = null;
  returned.value = null;
  try {
    const { authorize_url } = await startOAuthConnect(kind.name, { kind: kind.name, label, holder });
    window.location.assign(authorize_url);
  } catch (error) {
    connecting.value = null;
    connectionsSaid.value = { kind: kind.name, said: error instanceof ApiError && error.status === 503 ? 'not_set_up' : 'failed' };
  }
}
