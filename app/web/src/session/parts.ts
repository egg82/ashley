// The parts' sources on a signed-in person's screens: the house column and the cards brought up beside her words read
// the same ones.
import type { PartSources } from '../components/parts/registry';
import { houseAttention, houseControls, houseHome } from './house';
import { householdFacts } from './facts';
import { housePrinters } from './printers';

export const PERSON_SOURCES: PartSources = {
  controls: houseControls, home: houseHome, attention: houseAttention, printer: housePrinters, fact: householdFacts,
  conversation: () => null,
};
