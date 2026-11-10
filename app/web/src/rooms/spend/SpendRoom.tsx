// Usage, at bearing 125: what each provider has been used for and cost over today, the last 7 days and this month in the
// household's time zone, and what it says is left where it says anything.
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import type { SpendResponse } from '../../api/types';
import { dockIn } from '../../shell/her/dock';
import { day } from './format';
import { ProviderRow } from './ProviderRow';
import { RoutesPanel } from './RoutesPanel';
import { leaveRoom, loadSpend, spend, spendState } from './spend';

function Table({ s }: { s: SpendResponse }) {
  const now = new Date(s.as_of);
  const since = (name: string) => day(s.windows.find((w) => w.name === name)!.starts_at, s.zone);
  return (
    <div class="panel sp" role="table" aria-label="Usage by provider">
      <div class="sp-row sp-head" role="row">
        <span class="label" role="columnheader">Provider</span>
        <span class="label" role="columnheader" title={`since ${since('today')}`}>Today</span>
        <span class="label" role="columnheader" title={`since ${since('week')}`}>7 days</span>
        <span class="label" role="columnheader" title={`since ${since('month')}`}>This month</span>
        <span class="label" role="columnheader">Remaining</span>
      </div>
      {s.providers.map((p) => <ProviderRow key={p.provider} p={p} now={now} zone={s.zone} />)}
    </div>
  );
}

function Body() {
  const s = spend.value;
  if (spendState.value === 'failed' && !s) {
    return (
      <div class="panel set-down" role="alert">
        <div class="set-down-says">
          <b>Usage didn't load.</b>
          <button class="btn" type="button" onClick={() => void loadSpend()}>Try again</button>
        </div>
      </div>
    );
  }
  if (!s) return <span class="meta">Reading the ledger…</span>;
  return <Table s={s} />;
}

export function SpendRoom() {
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
  return (
    <div class="set sp-room" ref={here}>
      <div class="set-head">
        <h1>Usage</h1>
        <span class="set-dock" data-dock />
        <button class="btn sm ghost sp-refresh" type="button" disabled={spendState.value === 'loading'} onClick={() => void loadSpend()}>
          Refresh
        </button>
      </div>
      <div class="sp-body">
        <Body />
        {s && spendState.value === 'failed' && <span class="unk">couldn't refresh</span>}
        {s && (
          <p class="meta sp-foot">
            Cost is each provider's list price (prices.json) times the usage it reported; calls it gave no price for are counted, not costed.
            Days start at midnight in {s.zone}.
          </p>
        )}
        <RoutesPanel />
      </div>
    </div>
  );
}
