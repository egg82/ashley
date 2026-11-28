// The kiosk's data sources for the shared parts, backed by its signals and its cookie routes.
import { computed, signal } from '@preact/signals';
import type { AttentionSource, ControlsSource, FactSource, HomeSource, PrinterSource } from '../components/parts/sources';
import { controls, controlStates, glance, press } from './state';

export const kioskControls: ControlsSource = { controls, states: controlStates, press };
export const kioskHome: HomeSource = { home: computed(() => glance.value?.home) };
/** What needs a person is theirs, and the device's routes read none of it, so a kiosk shows it as unknown. */
export const kioskAttention: AttentionSource = { attention: signal(null) };
/** The device's routes read no printers, so a kiosk shows a printer as unknown. */
export const kioskPrinter: PrinterSource = { printers: signal(null), watch: () => () => undefined };
/** The device's routes read no one's facts, so a kiosk shows a fact as unknown. */
export const kioskFact: FactSource = { facts: signal(null), watch: () => () => undefined };
