// Whether a model is drawn as the four-view sheet a look photographs (true) or as the view a person orbits (false), and,
// in a look, the one side to draw it from instead of the sheet (`?view=` on the look's address).
import { createContext } from 'preact';
import type { ViewPreset } from './views';

export const AsSheet = createContext(false);
export const LookSide = createContext<ViewPreset | null>(null);
