// What the print check found on a model run's printed parts: the area each needs support under and whether it fits the
// bed, or why printing was not checked. A gap too small to print is a failed check, listed with the others above.
import type { RunReport } from '../../../api/types';
import { printPartText, printSkipText } from './modelFacts';

export function ModelPrint({ report }: { report: RunReport }) {
  const skipped = printSkipText(report.print, report.triangles);
  if (skipped || !report.print) return <p class="mprint meta">{skipped}</p>;
  const print = report.print;
  return (
    <ul class="mprint" aria-label="Printing">
      {print.printed.map((p) => (
        <li key={p.name}>
          <span class="mprint-name">{p.name}</span> <span class="meta">{printPartText(p, print)}</span>
        </li>
      ))}
    </ul>
  );
}
