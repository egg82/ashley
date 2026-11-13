// What the flow picture draws, worked out from the report: the tasks, the providers, and a flow for each task a provider
// answered. Only what had calls in the window is drawn; the ledger lists the quiet ones.
import type { SpendResponse, SpendTotals } from '../../api/types';
import { spanOf, usdOf, type Span } from './certainty.ts';
import { sumTotals } from './totals.ts';
import type { Win } from './window.ts';

export interface FlowNode {
  id: string;
  label: string;
  totals: SpendTotals;
  span: Span;
}

export interface Flow {
  /** `provider|task`, the key a pick and a path are named by. */
  id: string;
  provider: string;
  task: string;
  totals: SpendTotals;
  span: Span;
}

export interface FlowGraph {
  tasks: FlowNode[];
  providers: FlowNode[];
  flows: Flow[];
  /** The largest cost among the flows, which the widest cable is drawn for. 0 when no flow has a cost. */
  peak: number;
}

/** What is picked: a task, a provider, or one flow between them. */
export type Pick = { kind: 'task' | 'provider' | 'flow'; id: string };

export function samePick(a: Pick | null, b: Pick | null): boolean {
  return a !== null && b !== null && a.kind === b.kind && a.id === b.id;
}

/** Heavier first: more cost, then more calls; a figure with no cost sorts after every cost. */
export function heavier(a: { span: Span; totals: SpendTotals }, b: { span: Span; totals: SpendTotals }): number {
  const cost = (x: { span: Span }) => usdOf(x.span) ?? -1;
  return cost(b) - cost(a) || b.totals.calls - a.totals.calls;
}

export function flowGraph(s: SpendResponse, win: Win, nameOf: (task: string) => string): FlowGraph {
  const flows: Flow[] = [];
  const taskParts = new Map<string, SpendTotals[]>();
  const providers: FlowNode[] = [];
  for (const p of s.providers) {
    const totals = p.usage[win];
    if (totals.calls === 0) continue;
    providers.push({ id: p.provider, label: p.label, totals, span: spanOf(totals) });
    for (const k of p.tasks) {
      const u = k.usage[win];
      if (u.calls === 0) continue;
      flows.push({ id: `${p.provider}|${k.task}`, provider: p.provider, task: k.task, totals: u, span: spanOf(u) });
      taskParts.set(k.task, [...(taskParts.get(k.task) ?? []), u]);
    }
  }
  const tasks = [...taskParts].map(([id, parts]): FlowNode => {
    const totals = sumTotals(parts);
    return { id, label: nameOf(id), totals, span: spanOf(totals) };
  });
  tasks.sort((a, b) => heavier(a, b) || a.label.localeCompare(b.label));
  providers.sort((a, b) => heavier(a, b) || a.label.localeCompare(b.label));
  flows.sort(heavier);
  const peak = Math.max(0, ...flows.map((f) => usdOf(f.span) ?? 0));
  return { tasks, providers, flows, peak };
}

export type CableKind = 'measured' | 'partial' | 'unpriced' | 'noUsage';

/** How a flow's cable is drawn: solid, solid with a "?" where some calls are unknown, dashed, or dotted. */
export function cableKind(span: Span): CableKind {
  return span.kind === 'idle' ? 'noUsage' : span.kind;
}

/** Cable width is cost, by square root so a small flow stays visible beside the largest. Without a cost it is a thin fixed line. */
export function cableWidth(span: Span, peak: number): number {
  const usd = usdOf(span);
  if (usd === null) return 2.4;
  if (usd <= 0 || peak <= 0) return 1.6;
  return 1.6 + Math.sqrt(usd / peak) * 9.4;
}

/** Beads on a cable are calls, by log so one call shows and a thousand does not crowd. */
export function beadCount(calls: number): number {
  return Math.min(9, Math.max(1, Math.round(Math.log2(calls + 1))));
}

/** The flows a pick covers, which the rest of the picture dims around. */
export function flowsOf(g: FlowGraph, pick: Pick | null): Flow[] {
  if (!pick) return [];
  return g.flows.filter((f) => (pick.kind === 'task' ? f.task === pick.id : pick.kind === 'provider' ? f.provider === pick.id : f.id === pick.id));
}
