// Where the flow picture puts things at a given width: tasks down the left, providers down the right, one cable between
// each pair that had calls. Pure, so the geometry can be checked without a browser.
import type { FlowGraph } from './flowModel.ts';

const TASK_ROW = 25;
const PROVIDER_ROW = 42;
const PAD = 14;
const LEFT = 232;
const RIGHT = 200;

export interface FlowLayout {
  width: number;
  height: number;
  /** The x of the task nodes and of the provider nodes. */
  xTask: number;
  xProvider: number;
  taskY: Map<string, number>;
  providerY: Map<string, number>;
  /** A cable's path, from its task node to its provider node. */
  path: (flowId: string) => string;
}

function column(ids: string[], height: number): Map<string, number> {
  const step = (height - PAD * 2) / Math.max(ids.length, 1);
  return new Map(ids.map((id, i) => [id, PAD + step / 2 + i * step]));
}

export function layoutOf(g: FlowGraph, width: number): FlowLayout {
  const height = Math.max(g.tasks.length * TASK_ROW, g.providers.length * PROVIDER_ROW, 120) + PAD * 2;
  const xTask = Math.min(LEFT, width * 0.4);
  const xProvider = width - Math.min(RIGHT, width * 0.34);
  const taskY = column(g.tasks.map((t) => t.id), height);
  const providerY = column(g.providers.map((p) => p.id), height);
  // Cables that land on one provider are fanned a few pixels apart so each can be told from the next.
  const fan = new Map<string, number>();
  for (const p of g.providers) {
    const into = g.flows.filter((f) => f.provider === p.id).sort((a, b) => taskY.get(a.task)! - taskY.get(b.task)!);
    into.forEach((f, i) => fan.set(f.id, (i - (into.length - 1) / 2) * 3));
  }
  const path = (flowId: string): string => {
    const flow = g.flows.find((f) => f.id === flowId)!;
    const x1 = xTask + 9;
    const y1 = taskY.get(flow.task)!;
    const x2 = xProvider - 12;
    const y2 = providerY.get(flow.provider)! + (fan.get(flowId) ?? 0);
    const dx = (x2 - x1) * 0.55;
    return `M${x1} ${y1}C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`;
  };
  return { width, height, xTask, xProvider, taskY, providerY, path };
}
