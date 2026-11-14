// Connections, at bearing 250: the services she reaches. The summary and a map of her reach, then what needs a person, then
// each connection as a sentence grouped by what it gives her, then what could be added. Discord sends the person back to
// `?link=<outcome>` and a service connected through its own consent screen to `?connect=<outcome>`, each read once and
// dropped from the URL.
import { useLocation } from 'preact-iso';
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import { person } from '../../session/session';
import { dockIn } from '../../shell/her/dock';
import { CATALOGUE_PATH, isCataloguePath, settingsOf } from '../../shell/rooms';
import { loadAccounts, leaveRoom, loadState, outcomeOf, said } from './accounts';
import { connectionsState, held, kinds, loadConnections } from './connections';
import { connectOutcomeOf } from './connectOutcome';
import { CataloguePage } from './catalogue/CataloguePage';
import { Notice } from './Notice';
import { returned } from './oauth';
import { closePicker, openList, picking } from './picking';
import { PickerHost } from './Picker';
import { loadProtonAccounts, accounts as protonAccounts } from './proton';
import { AttentionCards } from './reach/AttentionCards';
import { CouldAdd } from './reach/CouldAdd';
import { groupsOf } from './reach/groups.ts';
import { Rail, type Jump } from './reach/Rail';
import { ReachGroup } from './reach/ReachGroup';
import { ReachMap } from './reach/ReachMap';
import { standingOf } from './reach/standing.ts';
import { removing } from './reach/state';
import { hasTalk, TalkGroup } from './reach/TalkGroup';
import { Down, Empty } from './reach/Unknown';
import { needOf } from './reach/needs.ts';
import { SettingsPage } from './settings/SettingsPage';

const SYNC_POLL_MS = 10_000;

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

/** The person whose hub the map draws: whoever holds the personal connections, else the signed-in person. */
function personName(): string {
  return held.value.find((c) => c.personal && c.added_by)?.added_by?.name ?? person.value?.name ?? 'You';
}

function Body() {
  const connections = held.value;
  const groups = groupsOf(connections);
  const standing = standingOf(connections, kinds.value);
  const needing = connections.some((c) => { const k = kinds.value.find((x) => x.name === c.kind); return k !== undefined && needOf(c, k) !== null; });
  const jumps: Jump[] = [
    ...(needing ? [{ id: 'needs-you', title: 'Needs you' }] : []),
    ...groups.map((g) => ({ id: `g-${g.id}`, title: g.title })),
    ...(hasTalk() ? [{ id: 'g-talk', title: 'Talking to her' }] : []),
    { id: 'g-add', title: 'Could be added' },
  ];
  return (
    <div class="rr-layout">
      <Rail standing={standing} jumps={jumps} />
      <div class="rr-main">
        {!picking.value && <Notice kinds={kinds.value} />}
        <ReachMap connections={connections} kinds={kinds.value} person={personName()} />
        <AttentionCards connections={connections} kinds={kinds.value} />
        {standing.total === 0 && <Empty />}
        {groups.map((g) => <ReachGroup key={g.id} group={g} kinds={kinds.value} />)}
        {hasTalk() && <TalkGroup />}
        <CouldAdd />
      </div>
    </div>
  );
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
  const accountsState = loadState.value;
  const state = connectionsState.value;
  const { path } = useLocation();
  const settingsId = settingsOf(path);
  const here = useRef<HTMLDivElement>(null);
  const failed = accountsState === 'unreachable' || accountsState === 'failed' || state === 'unreachable' || state === 'failed';
  const unreachable = accountsState === 'unreachable' || state === 'unreachable';
  const ready = !failed && state !== 'loading' && accountsState !== 'loading';
  // The room was docked into before its accounts arrived; each change of state lays out a new dock for her.
  useLayoutEffect(() => {
    const room = here.current?.closest('.room');
    if (room && !room.classList.contains('leaving')) dockIn(room, false);
  }, [accountsState, state]);
  if (isCataloguePath(path)) return <div class="set cn" ref={here}><CataloguePage /></div>;
  if (settingsId !== null) return <div class="set cn" ref={here}><SettingsPage id={settingsId} /></div>;
  return (
    <div class={`set cn rr-room${removing.value !== null ? ' removing' : ''}`} ref={here}>
      <div class="set-head">
        <h1>Connections</h1>
        {!failed && <span class="set-dock" data-dock />}
        {person.value?.admin && <a class="btn sm ghost cn-catalogue" href={CATALOGUE_PATH}>Model catalogue</a>}
        {ready && state === 'ready' && <button class="btn primary cn-add" type="button" onClick={openList}>Add a service</button>}
      </div>
      {!ready && !failed && <p class="set-none meta">Reading your accounts…</p>}
      {failed && <Down unreachable={unreachable} />}
      {ready && state === 'off' && <p class="set-none"><span class="unk">services can’t be connected here</span></p>}
      {ready && state === 'ready' && <Body />}
      <PickerHost />
    </div>
  );
}
