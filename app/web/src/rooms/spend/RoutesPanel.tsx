// Which model answers this household: for each chat-facing task, the deployment's routes or a model the household
// chose from them, tried first. The safety judge is shown, never chosen here.
import { useEffect } from 'preact/hooks';
import type { TaskRoutes } from '../../api/types';
import { chosenAt, routeName, taskName, unoffered } from './routeChoice';
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

function Choice({ t }: { t: TaskRoutes }) {
  const at = chosenAt(t);
  const first = t.routes[0];
  const pick = (value: string) => {
    const i = Number(value);
    void chooseRoute(t.task, i < 0 ? null : t.options[i]!);
  };
  return (
    <div class="sp-route" role="row">
      <label class="sp-route-name" role="cell" for={`sp-route-${t.task}`}><b>{taskName(t.task)}</b></label>
      <div class="sp-route-pick" role="cell">
        <select id={`sp-route-${t.task}`} value={String(at)} disabled={spendRoutesSaving.value}
          onChange={(e) => pick(e.currentTarget.value)}>
          <option value="-1">{first ? `As deployed: ${routeName(first)}` : 'As deployed'}</option>
          {t.options.map((o, i) => <option key={routeName(o)} value={String(i)}>{routeName(o)}</option>)}
        </select>
        {unoffered(t) && t.chosen && (
          <span class="unk">{routeName(t.chosen)} is no longer offered; replies use the deployment's models</span>
        )}
        {at >= 0 && <span class="meta">If it can't answer: {t.routes.map(routeName).join(', then ')}</span>}
      </div>
    </div>
  );
}

function Judge({ t }: { t: TaskRoutes }) {
  return (
    <div class="sp-route" role="row">
      <div class="sp-route-name" role="cell"><b>{taskName(t.task)}</b></div>
      <div class="sp-route-pick" role="cell">
        <span>{t.routes.map(routeName).join(', then ')}</span>
        <span class="meta">It decides whether a change she was not asked for goes ahead, so only whoever runs this deployment moves it.</span>
      </div>
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
    <section class="panel sp-routes" aria-label="Which model answers">
      <h2 class="label">Which model answers</h2>
      {!r && spendRoutesFailed.value && (
        <div class="sp-route-down">
          <span class="unk">couldn't read the model choices</span>
          <button class="btn sm ghost" type="button" onClick={() => void loadSpendRoutes()}>Try again</button>
        </div>
      )}
      {!r && !spendRoutesFailed.value && <span class="meta">Reading the model choices…</span>}
      {r && (
        <div role="table" aria-label="Model per task">
          {r.tasks.map((t) => (t.household ? <Choice key={t.task} t={t} /> : <Judge key={t.task} t={t} />))}
        </div>
      )}
      <Said />
      {r && <p class="meta sp-foot">A chosen model is tried first and the deployment's follow it. Its calls show above under its provider, at its own price.</p>}
    </section>
  );
}
