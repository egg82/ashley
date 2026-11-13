// One device's touch controls as an editor holds them: what is stored, the draft being edited, and the save.
import { useCallback, useEffect, useState } from 'preact/hooks';
import { getDeviceControls, putDeviceControls } from '../../api/deviceControls';
import type { DeviceControl } from '../../api/types';
import { onResync, onScreenChanged } from '../../session/live';
import { dirty, draftOf, REFUSED, type Row } from './controlRows';

export type Said = { tone: 'ok' | 'bad'; text: string };

export type Controls = {
  /** Null until the controls have been read; `failed` when they could not be. */
  rows: Row[] | null;
  failed: boolean;
  changed: boolean;
  busy: boolean;
  said: Said | null;
  edit: (next: Row[]) => void;
  save: () => Promise<void>;
  discard: () => void;
};

export function useControls(deviceId: number): Controls {
  const [stored, setStored] = useState<DeviceControl[] | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [version, setVersion] = useState(0);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<Said | null>(null);

  const adopt = (list: DeviceControl[], v: number) => {
    setStored(list);
    setRows(draftOf(list));
    setVersion(v);
  };
  const read = useCallback((then?: Said) => getDeviceControls(deviceId).then((got) => {
    adopt(got.device_controls, got.piece_version);
    setFailed(false);
    if (then) setSaid(then);
  }, () => setFailed(true)), [deviceId]);

  useEffect(() => {
    setRows(null);
    setSaid(null);
    void read();
    const again = () => void read();
    const stops = [onScreenChanged((device) => device === deviceId && again()), onResync(again)];
    return () => stops.forEach((stop) => stop());
  }, [deviceId]);

  const save = async () => {
    if (!rows) return;
    setBusy(true);
    try {
      const got = await putDeviceControls(deviceId, rows, version);
      if (got === 'stale') await read({ tone: 'bad', text: 'The list changed while you were editing it, so nothing was saved. This is what it is now.' });
      else if ('reason' in got) setSaid({ tone: 'bad', text: REFUSED[got.reason] });
      else {
        adopt(got.device_controls, got.piece_version);
        setSaid({ tone: 'ok', text: 'Saved. The screen has them on its next read.' });
      }
    } catch {
      setSaid({ tone: 'bad', text: "That didn't go through. Nothing changed." });
    }
    setBusy(false);
  };

  return {
    rows, failed, busy, said, save,
    changed: rows !== null && stored !== null && dirty(rows, stored),
    edit: (next) => { setRows(next); setSaid(null); },
    discard: () => { if (stored) setRows(draftOf(stored)); setSaid(null); },
  };
}
