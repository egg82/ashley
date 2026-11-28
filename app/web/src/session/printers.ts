// The household's printers as a signed-in person's cards read them (`api/house.ts`): read when a card first shows, then
// on a timer while any card shows and the page is visible, and on a turn on any thread. Nothing announces a print's
// progress, so the timer is what keeps a card current.
import { signal } from '@preact/signals';
import { ApiError } from '../api/client';
import { getHousePrinters } from '../api/house';
import type { HousePrinter } from '../api/types';
import type { PrinterSource } from '../components/parts/sources';
import { onThreadTurn } from './live';
import { load as reloadSession } from './session';

export const PRINTERS_MS = 30_000;

const printers = signal<readonly HousePrinter[] | null | undefined>(undefined);
let watchers = 0;
let stopAll: (() => void) | null = null;

async function read(): Promise<void> {
  try {
    printers.value = await getHousePrinters();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) void reloadSession();
    else printers.value = null;
  }
}

function start(): () => void {
  void read();
  const timer = setInterval(() => {
    if (!document.hidden) void read();
  }, PRINTERS_MS);
  const off = onThreadTurn(() => void read());
  return () => {
    clearInterval(timer);
    off();
  };
}

export const housePrinters: PrinterSource = {
  printers,
  watch() {
    watchers += 1;
    stopAll ??= start();
    return () => {
      watchers -= 1;
      if (watchers === 0 && stopAll) {
        stopAll();
        stopAll = null;
      }
    };
  },
};
