// The geometry of looking at a model, with no three.js in it so it loads with the page and is tested on its own. The
// frame is build123d's: millimetres, Z up, X right and Y away when looking at the front.
export type Vec3 = readonly [number, number, number];

export interface ViewPreset {
  id: 'iso' | 'front' | 'back' | 'left' | 'right' | 'top' | 'bottom';
  label: string;
  /** Where the camera sits relative to the model's centre, as a direction. */
  toward: Vec3;
  /** Which way is up on the screen; never along `toward`. */
  up: Vec3;
}

/** The sheet `bench_look` photographs, in reading order. */
export const VIEWS: readonly ViewPreset[] = [
  { id: 'iso', label: 'Isometric', toward: [1, -1, 0.9], up: [0, 0, 1] },
  { id: 'front', label: 'Front', toward: [0, -1, 0], up: [0, 0, 1] },
  { id: 'top', label: 'Top', toward: [0, 0, 1], up: [0, 1, 0] },
  { id: 'right', label: 'Right', toward: [1, 0, 0], up: [0, 0, 1] },
];

/** Every side she may ask `bench_look` to see a model from (`app/ashley/looks/views.json` lists the same ids); the sheet's
 * four are among them. */
export const SIDES: readonly ViewPreset[] = [
  VIEWS[0]!,
  VIEWS[1]!,
  { id: 'back', label: 'Back', toward: [0, 1, 0], up: [0, 0, 1] },
  { id: 'left', label: 'Left', toward: [-1, 0, 0], up: [0, 0, 1] },
  VIEWS[3]!,
  VIEWS[2]!,
  { id: 'bottom', label: 'Bottom', toward: [0, 0, -1], up: [0, -1, 0] },
];

/** The side named `id`, null when it is none of `SIDES`. */
export function sideNamed(id: string | null): ViewPreset | null {
  return SIDES.find((s) => s.id === id) ?? null;
}

/** How far from the centre a perspective camera must sit to see a sphere of `radius` whole, at vertical `fovDeg`. */
export function distanceToFit(radius: number, fovDeg: number, aspect: number): number {
  const half = (fovDeg * Math.PI) / 360;
  const narrow = aspect >= 1 ? half : Math.atan(Math.tan(half) * aspect);
  return radius / Math.sin(narrow);
}

/** Half the height of an orthographic frame that shows a sphere of `radius` whole with a margin, in a view `aspect` wide. */
export function orthoHalfHeight(radius: number, aspect: number): number {
  return (radius * 1.15) / Math.min(1, aspect);
}

function trim(n: number): string {
  return n.toFixed(Math.abs(n) >= 100 ? 0 : 1).replace(/\.0$/, '');
}

/** A model's extent as the person reads it: "120 × 80 × 40 mm". */
export function extentText(size: Vec3): string {
  return `${size.map(trim).join(' × ')} mm`;
}

/** The unit vector of `v`. */
export function unit(v: Vec3): Vec3 {
  const n = Math.hypot(...v);
  return [v[0] / n, v[1] / n, v[2] / n];
}
