// One provider: its three spans and what it has left. Opens in place to the same figures per task, and to why a balance
// is unknown with the page that says so.
import type { SpendProvider } from '../../api/types';
import { RemainingCell, UsageCell } from './Cells';

const KIND: Record<SpendProvider['kind'], string> = { paid: 'Paid', local: 'Local', unlisted: 'Not in the catalog' };

export function ProviderRow({ p, now, zone }: { p: SpendProvider; now: Date; zone: string }) {
  const b = p.balance;
  return (
    <details class="sp-prov" role="rowgroup">
      <summary class="sp-row" role="row">
        <div class="sp-name" role="cell">
          <b>{p.label}</b>
          <span class="pill">{KIND[p.kind]}</span>
        </div>
        <UsageCell label="Today" t={p.usage.today} />
        <UsageCell label="7 days" t={p.usage.week} />
        <UsageCell label="This month" t={p.usage.month} />
        <RemainingCell p={p} now={now} zone={zone} />
      </summary>
      {p.tasks.map((t) => (
        <div class="sp-row sp-task" role="row" key={t.task}>
          <div class="sp-name" role="cell"><span class="meta">{t.task}</span></div>
          <UsageCell label="Today" t={t.usage.today} />
          <UsageCell label="7 days" t={t.usage.week} />
          <UsageCell label="This month" t={t.usage.month} />
          <div class="sp-cell" />
        </div>
      ))}
      {p.tasks.length === 0 && <p class="meta sp-note">No calls in the last month.</p>}
      {b.state === 'unknown' && b.why && (
        <p class="meta sp-note">
          Remaining is unknown: {b.why}.{' '}
          {b.docs_url && <a href={b.docs_url} target="_blank" rel="noopener noreferrer">Billing documentation</a>}
        </p>
      )}
    </details>
  );
}
