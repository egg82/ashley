// Who changed which of a connection's settings, newest first; read again whenever a save changes the settings' revision.
import { useEffect, useState } from 'preact/hooks';
import { getSettingsHistory } from '../../../api/connectionSettings';
import type { SettingChange } from '../../../api/types';
import { locale } from '../../../household/format';
import { settings } from '../settings/state';
import { historyOf } from './settingsHistory.ts';

const when = (iso: string) => new Intl.DateTimeFormat(locale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(iso));

type Read = { state: 'loading' } | { state: 'failed' } | { state: 'ready'; changes: SettingChange[] };

function useRead(id: number, revision: number | undefined): [Read, () => void] {
  const [read, setRead] = useState<Read>({ state: 'loading' });
  const [tries, setTries] = useState(0);
  useEffect(() => {
    let live = true;
    getSettingsHistory(id)
      .then((history) => live && setRead({ state: 'ready', changes: history.changes }))
      .catch(() => live && setRead({ state: 'failed' }));
    return () => { live = false; };
  }, [id, revision, tries]);
  return [read, () => setTries(tries + 1)];
}

export function SettingsHistory({ id }: { id: number }) {
  const [read, retry] = useRead(id, settings.value?.revision);
  if (read.state === 'loading') return null;
  if (read.state === 'failed') {
    return <div class="dc-act"><span class="unk">couldn’t read who changed what</span><button class="btn sm ghost" type="button" onClick={retry}>Try again</button></div>;
  }
  const lines = historyOf(read.changes).slice(0, 5);
  if (lines.length === 0) return null;
  return (
    <ol class="rr-history" aria-label="Who changed what">
      {lines.map((l) => (
        <li key={l.id}><span>{l.who ?? <i>Someone who has since left</i>} changed {l.what}</span> <span class="meta">{when(l.at)}</span></li>
      ))}
    </ol>
  );
}
