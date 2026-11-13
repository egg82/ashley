// What we're working on: the person's open errands and benches, each with where it stands and a link to where it lives.
import { KIND_WORD, STATE_WORD, waiting, where } from './workRows';
import { moment } from '../memory/facts';
import type { WorkItem } from '../../api/types';
import { loadWork, work, workState } from './work';

function Row({ item }: { item: WorkItem }) {
  const href = where(item);
  const title = href ? <a class="work-title" href={href}>{item.title}</a> : <span class="work-title">{item.title}</span>;
  return (
    <li class={`work-row ${item.state}`}>
      {title}
      <span class="pill work-state">{STATE_WORD[item.state]}</span>
      <span class="meta work-meta">{KIND_WORD[item.kind]} · {moment(item.at)}</span>
    </li>
  );
}

export function WorkList() {
  const state = workState.value;
  const items = work.value;
  if (state === 'loading' && !items.length) return <p class="meta work-note">Reading…</p>;
  if (state !== 'ready' && !items.length) {
    return (
      <p class="work-note work-down" role="alert">
        <span class="meta">Couldn't read it.</span>
        <button class="btn sm ghost" type="button" onClick={() => void loadWork()}>Try again</button>
      </p>
    );
  }
  if (!items.length) return <p class="meta work-note">Nothing open.</p>;
  return <ul class="work-list">{items.map((i) => <Row key={`${i.kind}:${i.id}`} item={i} />)}</ul>;
}

/** The wide rail's panel. */
export function WorkPanel() {
  return (
    <aside class="panel work" aria-label="What we're working on">
      <div class="ph"><h3>Working on</h3></div>
      <WorkList />
    </aside>
  );
}

/** Below the rail's width: a closed fold above the history, naming how many wait on the person. */
export function WorkFold() {
  const items = work.value;
  const n = waiting(items);
  const unknown = workState.value !== 'ready' && !items.length;
  return (
    <details class="work-fold">
      <summary>
        <span>Working on</span>
        <span class="meta">{unknown ? '\u2014' : items.length}{n ? ` · ${n} waiting on you` : ''}</span>
      </summary>
      <WorkList />
    </details>
  );
}
