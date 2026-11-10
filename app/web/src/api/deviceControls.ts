// A device's touch controls: read, and replaced whole.
import { answer } from './client';
import type { ControlsRefused, DeviceControlList, DeviceControlWanted } from './types';

/** Device `id`'s controls in the order its screen shows them. A 404 is a device the household does not have. */
export async function getDeviceControls(id: number): Promise<DeviceControlList> {
  return answer(await fetch(`/api/devices/${id}/controls`), 200, 'GET /api/devices/{device_id}/controls');
}

/**
 * Replaces the whole of device `id`'s controls, as read at `baseVersion` (`DeviceControlList.version`). A 422 answers why
 * nothing was stored; a 409 is `'stale'`: the list changed since it was read, and nothing was stored.
 */
export async function putDeviceControls(id: number, wanted: DeviceControlWanted[], baseVersion: number): Promise<DeviceControlList | ControlsRefused | 'stale'> {
  const response = await fetch(`/api/devices/${id}/controls`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ wanted, base_version: baseVersion }),
  });
  if (response.status === 422) return (await response.json()) as ControlsRefused;
  if (response.status === 409) return 'stale';
  return answer(response, 200, 'PUT /api/devices/{device_id}/controls');
}
