// What a printer card says, from the printers read and the printer it names: pure, so it is tested without a page. A
// printer that cannot be read, or is missing from the read, is unknown; a printer that says nothing of its state is
// unknown too, never idle.
import type { HousePrinter } from '../../api/types';

export type PrinterStatus = 'reading' | 'unknown' | 'offline' | 'printing' | 'paused' | 'idle' | 'finished' | 'failed' | 'other';

export interface PrinterView {
  /** The printer's name, null when it is not known. */
  name: string | null;
  status: PrinterStatus;
  /** The printer's own word for a state this card has no name for. */
  word: string | null;
  job: string | null;
  /** 0 to 100, null when the printer does not say. */
  percent: number | null;
  minutesLeft: number | null;
  layer: string | null;
  problems: readonly string[];
}

const STATES: Record<string, PrinterStatus> = { RUNNING: 'printing', PAUSE: 'paused', IDLE: 'idle', FINISH: 'finished', FAILED: 'failed' };

const BLANK: Omit<PrinterView, 'status'> = { name: null, word: null, job: null, percent: null, minutesLeft: null, layer: null, problems: [] };

export function printerView(printers: readonly HousePrinter[] | null | undefined, ref: string): PrinterView {
  if (printers === undefined) return { ...BLANK, status: 'reading' };
  const found = printers?.find((p) => p.printer_id === ref);
  if (!found) return { ...BLANK, status: 'unknown' };
  const status = !found.online ? 'offline' : found.state === null ? 'unknown' : STATES[found.state] ?? 'other';
  const layer = found.layer !== null && found.layers !== null ? `${found.layer} / ${found.layers}` : null;
  return {
    name: found.name, status, word: status === 'other' ? found.state : null, job: found.print_name,
    percent: found.percent, minutesLeft: found.minutes_left, layer, problems: found.problems,
  };
}

/** Minutes as "1 h 05 m" or "12 m". */
export function minutes(m: number): string {
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} m` : `${m} m`;
}
