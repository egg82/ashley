// Usage, at bearing 125: what she has called and what it cost over today, this week and this month in the household's time
// zone, how sure each figure is, what each provider says is left, and which model answers each task.
import { useLocation } from 'preact-iso';
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import type { SpendResponse } from '../../api/types';
import { dockIn } from '../../shell/her/dock';
import { FlowSection } from './FlowSection';
import { timeOf } from './format';
import { Hero, WindowSwitch } from './Hero';
import { Ledger } from './LedgerSection';
import { unused } from './ledger';
import { Letter } from './LetterSection';
import { RoutesPanel } from './RoutesPanel';
import { leaveRoom, loadSpend, picked, spend, spendState } from './spend';
import { winOf, type Win } from './window';

function Down() {
  return (
    <div class="sp-down" role="alert">
      <b>Couldn't read what she has spent.</b>
      <span class="meta">Her usage ledger didn't answer, so there are no figures here. Try again.</span>
      <button class="btn sm" type="button" onClick={() => void loadSpend()}>Try again</button>
    </div>
  );
}

function Unused() {
  return (
    <div class="sp-none-yet">
      <b>Nothing to read yet.</b>
      <span class="meta">Once she has answered a request, her calls and what they cost appear here, and the first of the month starts a new ledger.</span>
    </div>
  );
}

function Read({ s, win }: { s: SpendResponse; win: Win }) {
  return (
    <>
      <Hero s={s} win={win} />
      <FlowSection s={s} win={win} />
      <Letter s={s} win={win} />
      <Ledger s={s} win={win} />
      <p class="meta sp-foot">Cost is each provider's list price times the usage it reported. Days start at midnight in {s.zone}.</p>
    </>
  );
}

export function SpendRoom() {
  const { query, route } = useLocation();
  const win = winOf(query.w);
  useEffect(() => {
    void loadSpend();
    return leaveRoom;
  }, []);
  const here = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const room = here.current?.closest('.room');
    if (room && !room.classList.contains('leaving')) dockIn(room, false);
  }, []);
  const s = spend.value;
  const failed = spendState.value === 'failed';
  const choose = (w: Win) => {
    picked.value = null;
    route(w === 'month' ? '/usage' : `/usage?w=${w}`, true);
  };
  return (
    <div class="set sp-room" ref={here}>
      <div class="set-head">
        <h1>Usage</h1>
        <span class="set-dock" data-dock />
        {s && !unused(s) && <WindowSwitch win={win} onPick={choose} />}
        <button class="btn sm ghost sp-refresh" type="button" disabled={spendState.value === 'loading'} onClick={() => void loadSpend()}>
          Refresh
        </button>
      </div>
      <div class="sp-body">
        {s && <span class="meta sp-asof">As of {timeOf(s.as_of, s.zone)} · {s.zone} time</span>}
        {failed && !s && <Down />}
        {!s && !failed && <span class="meta">Reading the ledger…</span>}
        {s && failed && <span class="sp-warn">Couldn't refresh; these figures are from {timeOf(s.as_of, s.zone)}.</span>}
        {s && (unused(s) ? <Unused /> : <Read s={s} win={win} />)}
        <RoutesPanel />
      </div>
    </div>
  );
}
