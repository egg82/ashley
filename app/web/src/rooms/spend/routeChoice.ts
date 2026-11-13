// How the model choices read: a task's name, a route's name, which option the chosen model is, and the order a call tries.
import type { RouteModel, TaskRoutes } from '../../api/types';

const TASK: Record<string, string> = {
  command: 'Command',
  chat: 'Chat',
  brainstorm: 'Brainstorm',
  escalated: 'Escalated',
  wrap_up: 'Wrap-up',
  memory_write: 'Memory write',
  memory_judge: 'Memory judge',
  look_up: 'Look up',
  bench_tidy: 'Bench tidy',
  errand: 'Errand',
  action_judge: 'Action judge',
  bench_job: 'Bench job',
  eval_judge: 'Eval judge',
  speak: 'Speak',
  embed: 'Embed',
  voiceprint: 'Voiceprint',
  transcribe: 'Transcribe',
};

/** The task as a person reads it; a task with no name here is its id with the underscores read as spaces. */
export function taskName(task: string): string {
  if (TASK[task]) return TASK[task];
  const spaced = task.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** A route as `model (provider)`. */
export function routeName(r: RouteModel): string {
  return `${r.model} (${r.provider})`;
}

const same = (a: RouteModel, b: RouteModel) => a.provider === b.provider && a.model === b.model;

/** Where the task's chosen model sits in its options: -1 for none, and also for a choice no longer offered. */
export function chosenAt(t: TaskRoutes): number {
  const c = t.chosen;
  return c ? t.options.findIndex((o) => same(o, c)) : -1;
}

/** Whether the task's chosen model is one it no longer offers, so its call goes to the deployment's routes. */
export function unoffered(t: TaskRoutes): boolean {
  return t.chosen !== null && chosenAt(t) === -1;
}

/** The models a call tries, in order: the household's choice, then the deployment's routes. */
export function chainOf(t: TaskRoutes): RouteModel[] {
  const chain = t.chosen && !unoffered(t) ? [t.chosen, ...t.routes] : t.routes;
  return chain.filter((r, i) => chain.findIndex((o) => same(o, r)) === i);
}

export interface Choice {
  value: string;
  label: string;
}

/** The select's entries: her default first (value -1, which clears the choice), then the other offered models by option index. */
export function choicesOf(t: TaskRoutes): Choice[] {
  const first = t.routes[0];
  const rest = t.options.flatMap((o, i) => (first && same(o, first) ? [] : [{ value: String(i), label: routeName(o) }]));
  return [{ value: '-1', label: first ? `${first.model} (her default)` : 'Her default' }, ...rest];
}

/** The select's value: her default for no choice, for a choice no longer offered, and for a choice that is her default. */
export function selectedOf(t: TaskRoutes): string {
  const first = t.routes[0];
  if (!t.chosen || (first && same(t.chosen, first))) return '-1';
  return String(chosenAt(t));
}
