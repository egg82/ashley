// Memory, at bearing 315: what she knows about the person signed in, newest first. "New this week" leads; then
// everything else, filtered by kind; the household's facts have their own tab, the person's reminders theirs, and what
// she did on her own (`OutsideTab.tsx`) a third.
// Tab, kind and search live in the URL.
import { useLocation } from 'preact-iso';
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import type { FactKind, MemoryFact } from '../../api/types';
import { KIND_LABEL } from '../../components/FactParts';
import { dockIn } from '../../shell/her/dock';
import { herWord } from '../../shell/her/state';
import { FactCard } from './FactCard';
import { FactRow } from './FactRow';
import { isNew, KINDS, matching, tabOf, type RoomTab, type Tab } from './facts';
import { corrected, facts, leaveRoom, loadFacts, loadState, note, selected } from './memory';
import { OutsideList } from './OutsideTab';
import { loadOutside, outside, outsideState } from './outside';
import { Rail } from './Rail';
import { RemindersList } from './RemindersTab';
import { loadReminders, reminders, remindersState } from './reminders';

interface View {
  tab: RoomTab;
  kind: FactKind | null;
  q: string;
}
type SetView = (next: Partial<View>) => void;

const NOTE_MS = 4200;

function useView(): [View, SetView] {
  const { query, route } = useLocation();
  const view: View = {
    tab: query.tab === 'household' || query.tab === 'reminders' || query.tab === 'outside' ? query.tab : 'you',
    kind: KINDS.find((k) => k === query.kind) ?? null,
    q: query.q ?? '',
  };
  const set: SetView = (next) => {
    const v = { ...view, ...next };
    const p = new URLSearchParams();
    if (v.tab !== 'you') p.set('tab', v.tab);
    if (v.kind) p.set('kind', v.kind);
    if (v.q) p.set('q', v.q);
    const s = p.toString();
    route(`/memory${s ? `?${s}` : ''}`, true);
  };
  return [view, set];
}

function Tabs({ view, set, all }: { view: View; set: SetView; all: readonly MemoryFact[] }) {
  const tab = (t: Tab, label: string) => (
    <button type="button" aria-pressed={view.tab === t} onClick={() => set({ tab: t, kind: null })}>
      {label} <span class="meta">{all.filter((f) => tabOf(f) === t).length}</span>
    </button>
  );
  const ready = remindersState.value === 'ready';
  return (
    <div class="seg">
      {tab('you', 'About you')}
      {tab('household', 'Household')}
      <button type="button" aria-pressed={view.tab === 'reminders'} onClick={() => set({ tab: 'reminders', kind: null, q: '' })}>
        Reminders {ready && <span class="meta">{reminders.value.length}</span>}
      </button>
      <button type="button" aria-pressed={view.tab === 'outside'} onClick={() => set({ tab: 'outside', kind: null, q: '' })}>
        On her own {outsideState.value === 'ready' && <span class="meta">{outside.value.length}</span>}
      </button>
    </div>
  );
}

function Kinds({ view, set, rest }: { view: View; set: SetView; rest: readonly MemoryFact[] }) {
  const pill = (kind: FactKind | null, label: string, n: number) => (
    <button key={kind ?? 'all'} type="button" class={`pill${view.kind === kind ? ' on' : ''}`} aria-pressed={view.kind === kind} onClick={() => set({ kind })}>
      {label} {n}
    </button>
  );
  const present = KINDS.filter((k) => rest.some((f) => f.kind === k));
  return (
    <div class="kinds">
      {pill(null, 'All', rest.length)}
      {present.map((k) => pill(k, KIND_LABEL[k], rest.filter((f) => f.kind === k).length))}
    </div>
  );
}

function Down({ failed }: { failed: boolean }) {
  return (
    <div class="panel mem-down" role="alert">
      <span class="down-dock" data-dock />
      <div class="mem-down-says">
        {!failed && <span class="her-word unreachable">{herWord.value}</span>}
        <b>{failed ? "Her memory didn't load." : "Can't reach her memory right now."}</b>
        <button class="btn" type="button" onClick={() => void loadFacts()}>Try again</button>
      </div>
    </div>
  );
}

function Lists({ view, set, mine }: { view: View & { tab: Tab }; set: SetView; mine: readonly MemoryFact[] }) {
  const whose = view.tab === 'household' ? 'the household' : 'you';
  if (!mine.length) {
    return (
      <div class="mem-empty">
        <span class="down-dock" data-dock />
        <div class="mem-down-says">
          <b>She doesn't know anything about {whose} yet.</b>
          <span class="meta">What she learns in conversations shows up here.</span>
        </div>
      </div>
    );
  }
  const now = Date.now();
  const shown = matching(mine, view.q);
  const fresh = shown.filter((f) => isNew(f, now));
  const rest = shown.filter((f) => !isNew(f, now));
  const rows = view.kind ? rest.filter((f) => f.kind === view.kind) : rest;
  return (
    <>
      <div class="sec-title"><b>New this week</b><span class="label">check these first</span></div>
      {fresh.length ? (
        <div class="newgrid">{fresh.map((f) => <FactCard key={f.id} fact={f} fresh={corrected.value.has(f.id)} />)}</div>
      ) : (
        <p class="mem-none meta">{view.q ? 'Nothing new this week matches.' : 'Nothing new this week.'}</p>
      )}
      <div class="sec-title"><b>Everything she knows about {whose}</b>{rest.length > 0 && <Kinds view={view} set={set} rest={rest} />}</div>
      {rows.length ? (
        <div class="rows">{rows.map((f) => <FactRow key={f.id} fact={f} fresh={corrected.value.has(f.id)} />)}</div>
      ) : (
        <p class="mem-none meta">{view.q ? `No older fact says “${view.q}”.` : 'Nothing older than a week.'}</p>
      )}
    </>
  );
}

function Note() {
  const n = note.value;
  useEffect(() => {
    if (!n) return;
    const t = setTimeout(() => (note.value = null), NOTE_MS);
    return () => clearTimeout(t);
  }, [n]);
  return <div class={`toast${n?.forgot ? ' forgot' : ''}`} role="status" hidden={!n}>{n?.text}</div>;
}

export function MemoryRoom() {
  const [view, set] = useView();
  useEffect(() => {
    void loadFacts();
    void loadReminders();
    void loadOutside();
    return leaveRoom;
  }, []);
  const state = loadState.value;
  const here = useRef<HTMLDivElement>(null);
  // The room was docked into before its facts arrived; each change of state lays out a new dock for her.
  useLayoutEffect(() => {
    const room = here.current?.closest('.room');
    if (room && !room.classList.contains('leaving')) dockIn(room, false);
  }, [state]);
  const factTab = view.tab === 'reminders' || view.tab === 'outside' ? null : view.tab;
  const mine = facts.value.filter((f) => tabOf(f) === factTab);
  const chosen = mine.find((f) => f.id === selected.value) ?? mine[0];
  return (
    <>
      <div class="mem" ref={here}>
        <div class="mem-main">
          <div class="mem-head">
            <h1>Memory</h1>
            {state === 'ready' && <Tabs view={view} set={set} all={facts.value} />}
            {state === 'ready' && factTab && (
              <label class="search">
                <input type="search" value={view.q} placeholder="Find a fact" aria-label="Find a fact" onInput={(e) => set({ q: e.currentTarget.value })} />
              </label>
            )}
          </div>
          {state === 'loading' && <p class="mem-none meta">Reading her memory…</p>}
          {(state === 'unreachable' || state === 'failed') && <Down failed={state === 'failed'} />}
          {state === 'ready' && factTab && <Lists view={{ ...view, tab: factTab }} set={set} mine={mine} />}
          {state === 'ready' && view.tab === 'reminders' && <RemindersList />}
          {state === 'ready' && view.tab === 'outside' && <OutsideList />}
        </div>
        {state === 'ready' && factTab && chosen && <Rail fact={chosen} />}
      </div>
      <span id="forget-how" hidden>Hold for about a second. It deletes the fact and its history for good.</span>
      <Note />
    </>
  );
}
