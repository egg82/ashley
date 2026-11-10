// A model run's checks, each judged by the app from the script's numbers and the source of the measurements it rests on:
// pass, fail, or unconfirmed (it would pass, but rests on a guess or a measurement the run did not have), which is
// hatched as a guess is on the measurements table.
import type { ReportCheck, RunReport } from '../../../api/types';
import { checkText, tally } from './modelFacts';

const WORD: Record<ReportCheck['verdict'], string> = { pass: 'pass', fail: 'fail', unconfirmed: 'unconfirmed' };

function Row({ check }: { check: ReportCheck }) {
  return (
    <li class="mcheck" data-verdict={check.verdict}>
      <span class="mcheck-v">{WORD[check.verdict]}</span>
      <span class="mcheck-name">{check.name}</span>
      <span class="mcheck-num num">{checkText(check)}</span>
      {check.rests_on.length > 0 && <span class="mcheck-on meta">rests on {check.rests_on.join(', ')}</span>}
    </li>
  );
}

export function ModelChecks({ report }: { report: RunReport | null }) {
  if (!report) return <p class="meta">The last run left no report, so nothing was checked.</p>;
  if (!report.checks.length) return <p class="meta">The script made no checks.</p>;
  const n = tally(report.checks);
  return (
    <div class="mchecks">
      <p class="mchecks-sum meta">
        {n.pass} pass · {n.fail} fail · {n.unconfirmed} unconfirmed
      </p>
      <ul>{report.checks.map((c) => <Row key={c.name} check={c} />)}</ul>
    </div>
  );
}
