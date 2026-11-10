// How the model choices read: a route's name, and which option a task's chosen model is.
import type { RouteModel, TaskRoutes } from '../../api/types';

const TASK: Record<string, string> = {
  command: 'Short commands',
  chat: 'Conversation',
  brainstorm: 'Long thinking and escalations',
  action_judge: 'Safety judge',
};

/** The task as a person reads it; a task with no name here is shown by its id. */
export function taskName(task: TaskRoutes['task']): string {
  return TASK[task] ?? task;
}

/** A route as `model (provider)`. */
export function routeName(r: RouteModel): string {
  return `${r.model} (${r.provider})`;
}

/** Where the task's chosen model sits in its options: -1 for none, and also for a choice no longer offered. */
export function chosenAt(t: TaskRoutes): number {
  const c = t.chosen;
  return c ? t.options.findIndex((o) => o.provider === c.provider && o.model === c.model) : -1;
}

/** Whether the task's chosen model is one it no longer offers, so its call goes to the deployment's routes. */
export function unoffered(t: TaskRoutes): boolean {
  return t.chosen !== null && chosenAt(t) === -1;
}
