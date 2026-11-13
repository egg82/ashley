// A connection's settings in the opened row: what each holds and who last changed it, the ones that decide what she trusts
// first, the changelog beneath. Changing them is the settings page; Home Assistant's counts line leads.
import { useEffect, useState } from 'preact/hooks';
import { getSettings, getSettingsHistory } from '../../../api/connectionSettings';
import type { ConnectionSettings, SettingChange } from '../../../api/types';
import { locale } from '../../../household/format';
import { summaryOf } from '../settings/summary';
import { digestOf, historyOf } from './settingsDigest.ts';

const day = (iso: string) => new Intl.DateTimeFormat(locale(), { month: 'short', day: 'numeric' }).format(new Date(iso));
const when = (iso: string) => new Intl.DateTimeFormat(locale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(iso));

type Read = { state: 'loading' } | { state: 'failed' } | { state: 'ready'; settings: ConnectionSettings; changes: SettingChange[] };

function useRead(id: number): [Read, () => void] {
  const [read, setRead] = useState<Read>({ state: 'loading' });
  const [tries, setTries] = useState(0);
  useEffect(() => {
    let live = true;
    setRead({ state: 'loading' });
    Promise.all([getSettings(id), getSettingsHistory(id)])
      .then(([settings, history]) => live && setRead({ state: 'ready', settings, changes: history.changes }))
      .catch(() => live && setRead({ state: 'failed' }));
    return () => { live = false; };
  }, [id, tries]);
  return [read, () => setTries(tries + 1)];
}

function Who({ by, at }: { by: { name: string | null } | null; at: string | null }) {
  if (by === null || at === null) return <span class="unk">no change recorded</span>;
  return <span class="meta">last changed by {by.name ?? <i>someone who has since left</i>}, {day(at)}</span>;
}

export function SettingsDigest({ id }: { id: number }) {
  const [read, retry] = useRead(id);
  if (read.state === 'loading') return <p class="meta">Reading the settings…</p>;
  if (read.state === 'failed') {
    return <div class="dc-act"><span class="unk">couldn’t read the settings</span><button class="btn sm ghost" type="button" onClick={retry}>Try again</button></div>;
  }
  const rows = digestOf(read.settings.settings, read.settings.values, read.changes);
  const lines = historyOf(read.changes).slice(0, 5);
  return (
    <div class="rr-settings">
      <p class="cn-blurb">{summaryOf(read.settings.values)}</p>
      <ul class="rr-set-rows">
        {rows.map((r) => (
          <li key={r.key} class={r.judging ? 'judging' : ''}>
            <span class="rr-set-title">{r.title}</span>
            <span class="meta">{r.decides} · {r.count} {r.count === 1 ? 'entry' : 'entries'}</span>
            <Who by={r.by} at={r.at} />
          </li>
        ))}
      </ul>
      <a class="btn sm" href={`/connections/${id}/settings`}>Change settings</a>
      {lines.length > 0 && (
        <ol class="rr-history" aria-label="Who changed what">
          {lines.map((l) => (
            <li key={l.id}><span>{l.who ?? <i>Someone who has since left</i>} changed {l.what}</span> <span class="meta">{when(l.at)}</span></li>
          ))}
        </ol>
      )}
    </div>
  );
}
