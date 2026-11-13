// Who answers: for each task, a sentence ("Chat is answered by [model]") with the fallbacks in a quiet line under it. A
// household chooses among the models the deployment offers; the safety judge is shown with why it is fixed.
import { useEffect } from 'preact/hooks';
import type { TaskRoutes } from '../../api/types';
import { chainOf, choicesOf, routeName, selectedOf, taskName, unoffered } from './routeChoice';
import { chooseRoute, loadSpendRoutes, spendRoutes, spendRoutesFailed, spendRoutesSaid, spendRoutesSaving } from './spendRoutes';

const SAID: Record<NonNullable<typeof spendRoutesSaid.value>, [string, 'ok' | 'bad']> = {
  saved: ['Saved. Every reply uses it within half a minute.', 'ok'],
  not_household: ['A household does not choose the model for that task, so nothing was saved.', 'bad'],
  not_offered: ['That model is no longer offered, so nothing was saved.', 'bad'],
  unwired: ["That model's provider has no key right now, so nothing was saved.", 'bad'],
  failed: ["That didn't go through. Nothing changed.", 'bad'],
};

function Said() {
  const s = spendRoutesSaid.value;
  if (!s) return null;
  const [text, tone] = SAID[s];
  return (
    <div class={`dc-note ${tone}`} role={tone === 'bad' ? 'alert' : 'status'}>
      <span>{text}</span>
      <button class="btn sm ghost" type="button" onClick={() => (spendRoutesSaid.value = null)}>Dismiss</button>
    </div>
  );
}

function Fallbacks({ t }: { t: TaskRoutes }) {
  const rest = chainOf(t).slice(1);
  if (rest.length === 0) return null;
  return <span class="meta sp-then">If that fails she tries {rest.map((r) => r.model).join(', then ')}.</span>;
}

function Choice({ t }: { t: TaskRoutes }) {
  const id = `sp-route-${t.task}`;
  return (
    <div class="sp-says">
      <p>
        <label for={id}>{taskName(t.task)}</label> is answered by{' '}
        <select id={id} value={selectedOf(t)} disabled={spendRoutesSaving.value}
          onChange={(e) => {
            const i = Number(e.currentTarget.value);
            void chooseRoute(t.task, i < 0 ? null : t.options[i]!);
          }}>
          {choicesOf(t).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </p>
      {unoffered(t) && t.chosen && <span class="sp-warn">{routeName(t.chosen)} is no longer offered; replies use her default.</span>}
      <Fallbacks t={t} />
    </div>
  );
}

function Fixed({ t }: { t: TaskRoutes }) {
  const first = t.routes[0];
  return (
    <div class="sp-says">
      <p>{taskName(t.task)} is answered by <code>{first ? first.model : 'no model'}</code></p>
      <Fallbacks t={t} />
      <span class="meta sp-then">Fixed. It decides whether a change she wasn't asked for goes ahead, so only whoever runs this deployment moves it.</span>
    </div>
  );
}

export function RoutesPanel() {
  useEffect(() => {
    void loadSpendRoutes();
    return () => void (spendRoutesSaid.value = null);
  }, []);
  const r = spendRoutes.value;
  return (
    <section class="sp-who" aria-label="Who answers">
      <h2 class="label">Who answers</h2>
      {!r && spendRoutesFailed.value && (
        <div class="sp-down" role="alert">
          <b>Couldn't read her model choices.</b>
          <span class="meta">Nothing has changed. Try again.</span>
          <button class="btn sm" type="button" onClick={() => void loadSpendRoutes()}>Try again</button>
        </div>
      )}
      {!r && !spendRoutesFailed.value && <span class="meta">Reading the model choices…</span>}
      {r && r.choices.length === 0 && <p class="meta">No models are offered yet. Once she is connected to one, you choose here which answers chat.</p>}
      {r?.choices.map((t) => (t.household ? <Choice key={t.task} t={t} /> : <Fixed key={t.task} t={t} />))}
      <Said />
      {r && r.choices.length > 0 && <p class="meta sp-foot">A model you choose is tried first. What it costs shows in the ledger under its provider, at its own price.</p>}
    </section>
  );
}
