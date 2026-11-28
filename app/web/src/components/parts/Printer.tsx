// A printer's card: its name, what it is doing, the print it is on with how far along and how long is left, and any
// faults it reports. Unknown reads as unknown, never as idle. `PrinterCard` is pure; `Printer` keeps the read fresh.
import { useEffect } from 'preact/hooks';
import { minutes, printerView, type PrinterStatus } from './printerView';
import type { PrinterSource } from './sources';

const SAID: Record<PrinterStatus, string> = {
  reading: 'Reading…', unknown: 'unknown', offline: 'Offline', printing: 'Printing', paused: 'Paused', idle: 'Idle',
  finished: 'Finished', failed: 'Failed', other: '',
};

export function PrinterCard({ source, printerId }: { source: PrinterSource; printerId: string }) {
  const view = printerView(source.printers.value, printerId);
  const said = view.status === 'other' ? view.word ?? '' : SAID[view.status];
  return (
    <section class={`k-printer ${view.status}`} aria-label={view.name ? `Printer ${view.name}` : 'Printer'}>
      <div class="k-printer-top">
        <h2 class="label">{view.name ?? 'Printer'}</h2>
        <span class={view.status === 'unknown' ? 'unk' : 'k-printer-state'}>{said}</span>
      </div>
      {view.job && <p class="k-printer-job">{view.job}</p>}
      {view.percent !== null && (
        <div class="k-printer-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(view.percent)}>
          <i style={{ width: `${Math.min(100, Math.max(0, view.percent))}%` }} />
        </div>
      )}
      {(view.percent !== null || view.minutesLeft !== null || view.layer) && (
        <p class="meta k-printer-meta">
          {[view.percent !== null && `${Math.round(view.percent)}%`, view.minutesLeft !== null && `${minutes(view.minutesLeft)} left`,
            view.layer && `layer ${view.layer}`].filter(Boolean).join(' · ')}
        </p>
      )}
      {view.problems.length > 0 && (
        <ul class="k-printer-faults">{view.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
      )}
    </section>
  );
}

/** The card, keeping its source's printers read while it is shown. */
export function Printer({ source, printerId }: { source: PrinterSource; printerId: string }) {
  useEffect(() => source.watch(), [source]);
  return <PrinterCard source={source} printerId={printerId} />;
}
