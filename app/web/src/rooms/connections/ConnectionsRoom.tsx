// Connections, at bearing 250: the services she is linked to. Yours (your Discord account, your code hosts and sessions)
// and The household's (its finances, its house). Discord sends the person back to `?link=<outcome>` and a service connected through its own
// consent screen to `?connect=<outcome>`, each read once and dropped from the URL. Anything not connected yet is added from one picker.
import { useLocation } from 'preact-iso';
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import { dockIn } from '../../shell/her/dock';
import { settingsOf } from '../../shell/rooms';
import { herWord } from '../../shell/her/state';
import { loadAccounts, leaveRoom, loadState, outcomeOf, said } from './accounts';
import { connectionsState, kinds, loadConnections } from './connections';
import { Notice } from './Notice';
import { connectOutcomeOf } from './connectOutcome';
import { returned } from './oauth';
import { closePicker, openList, picking } from './picking';
import { PickerHost } from './Picker';
import { loadProtonAccounts, accounts as protonAccounts } from './proton';
import { Household, Yours } from './Section';
import { SettingsPage } from './settings/SettingsPage';

const SYNC_POLL_MS = 10_000;

function Down({ failed }: { failed: boolean }) {
  return (
    <div class="panel set-down" role="alert">
      <span class="down-dock" data-dock />
      <div class="set-down-says">
        {!failed && <span class="her-word unreachable">{herWord.value}</span>}
        <b>{failed ? "Your accounts didn't load." : "Can't reach her right now."}</b>
        <button class="btn" type="button" onClick={() => void loadAccounts()}>Try again</button>
      </div>
    </div>
  );
}

function useReturn(): void {
  const { query, route } = useLocation();
  useEffect(() => {
    const link = outcomeOf(query.link);
    const connect = connectOutcomeOf(query.connect);
    if (!link && !connect) return;
    if (link) said.value = link;
    if (connect) returned.value = connect;
    route('/connections', true);
  }, [query.link, query.connect]);
}

/** Reads Bridge's accounts once the connections are, and again every few seconds while any is still syncing. */
function useProtonAccounts(): void {
  const ready = connectionsState.value === 'ready' && kinds.value.some((k) => k.connect === 'bridge');
  const syncing = [...protonAccounts.value.values()].some((a) => a.syncing);
  useEffect(() => {
    if (ready) void loadProtonAccounts();
  }, [ready]);
  useEffect(() => {
    if (!ready || !syncing) return;
    const timer = window.setInterval(() => void loadProtonAccounts(), SYNC_POLL_MS);
    return () => window.clearInterval(timer);
  }, [ready, syncing]);
}

export function ConnectionsRoom() {
  useReturn();
  useProtonAccounts();
  useEffect(() => {
    void loadAccounts();
    void loadConnections();
    return () => {
      closePicker();
      leaveRoom();
    };
  }, []);
  const state = loadState.value;
  const settingsId = settingsOf(useLocation().path);
  const here = useRef<HTMLDivElement>(null);
  // The room was docked into before its accounts arrived; each change of state lays out a new dock for her.
  useLayoutEffect(() => {
    const room = here.current?.closest('.room');
    if (room && !room.classList.contains('leaving')) dockIn(room, false);
  }, [state]);
  if (settingsId !== null) return <div class="set cn" ref={here}><SettingsPage id={settingsId} /></div>;
  return (
    <div class="set cn" ref={here}>
      <div class="set-head">
        <h1>Connections</h1>
        {state !== 'unreachable' && state !== 'failed' && <span class="set-dock" data-dock />}
        {state === 'ready' && <button class="btn primary cn-add" type="button" onClick={openList}>Add a service</button>}
      </div>
      {state === 'loading' && <p class="set-none meta">Reading your accounts…</p>}
      {(state === 'unreachable' || state === 'failed') && <Down failed={state === 'failed'} />}
      {state === 'ready' && (
        <div class="cn-body">
          {!picking.value && <Notice kinds={kinds.value} />}
          <Yours />
          <Household />
        </div>
      )}
      <PickerHost />
    </div>
  );
}
