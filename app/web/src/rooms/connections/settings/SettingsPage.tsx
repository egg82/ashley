// A connection's settings, which are Home Assistant's alone today. Opened at
// `/connections/<id>/settings`, so a reload or a shared link lands here. Saving replaces the whole of them.
import { useEffect } from 'preact/hooks';
import { locale } from '../../../household/format';
import { held, kinds } from '../connections';
import { HaSettings } from './HaSettings';
import { dirty, discard, loadHouse, loadSettings, loaded, said, save, saving, settings } from './state';

const changedAt = (iso: string) => new Intl.DateTimeFormat(locale(), { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso));

const SAID: Record<NonNullable<typeof said.value>, string> = {
  saved: 'Saved.',
  conflict: 'These changed somewhere else since you opened them.',
  refused: 'Some of that isn’t a value these settings take.',
  failed: 'That didn’t save.',
};

function Foot({ id }: { id: number }) {
  const read = settings.value;
  const state = said.value;
  const changed = dirty();
  return (
    <div class="cn-savebar">
      {state && <span class={state === 'saved' ? 'meta' : 'cn-needs'} role="status">{SAID[state]}</span>}
      {state === 'conflict' && <button class="btn sm" type="button" onClick={() => void loadSettings(id)}>Reload</button>}
      {!state && read?.updated_at && (
        <span class="meta">Last changed {changedAt(read.updated_at)}{read.updated_by ? ` by ${read.updated_by.name}` : ''}</span>
      )}
      {!state && read && !read.updated_at && <span class="meta">Not set yet</span>}
      <span class="cn-save-acts">
        <button class="btn sm ghost" type="button" disabled={!changed || saving.value} onClick={discard}>Discard</button>
        <button class="btn sm primary" type="button" disabled={!changed || saving.value} onClick={() => void save(id)}>
          {saving.value ? 'Saving…' : 'Save'}
        </button>
      </span>
    </div>
  );
}

function Body({ id }: { id: number }) {
  switch (loaded.value) {
    case 'loading':
      return <p class="set-none meta">Reading the settings…</p>;
    case 'missing':
      return <p class="set-none meta"><span class="unk">no settings for this connection</span></p>;
    case 'failed':
      return (
        <div class="dc-act">
          <span class="unk">couldn’t read the settings</span>
          <button class="btn sm ghost" type="button" onClick={() => void loadSettings(id)}>Try again</button>
        </div>
      );
    case 'ready':
      return (
        <>
          <HaSettings id={id} />
          <Foot id={id} />
        </>
      );
  }
}

export function SettingsPage({ id }: { id: number }) {
  useEffect(() => {
    void loadSettings(id);
    void loadHouse(id);
  }, [id]);
  const connection = held.value.find((c) => c.id === id);
  const kind = kinds.value.find((k) => k.name === (connection?.kind ?? settings.value?.kind));
  const title = connection?.label || kind?.title || 'Connection';
  return (
    <>
      <div class="set-head">
        <h1>{title} settings</h1>
        <span class="set-dock" data-dock />
        <a class="btn sm ghost cn-back" href="/connections">Connections</a>
      </div>
      <div class="cn-body"><Body id={id} /></div>
    </>
  );
}
