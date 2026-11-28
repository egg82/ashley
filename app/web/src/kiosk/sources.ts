// The kiosk's data sources for the shared parts, backed by its signals and its cookie routes.
import { computed } from '@preact/signals';
import type { ControlsSource, HomeSource } from '../components/parts/sources';
import { controls, controlStates, glance, press } from './state';

export const kioskControls: ControlsSource = { controls, states: controlStates, press };
export const kioskHome: HomeSource = { home: computed(() => glance.value?.home) };
