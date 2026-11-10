// Mermaid source to an SVG string or the parser's own message. Mermaid is imported on first use, so a bench with no
// diagram never loads it. Nothing here touches the page, so it runs against a stand-in for Mermaid in the tests.

export type Drawn = { is: 'svg'; svg: string } | { is: 'error'; message: string };

/** The part of Mermaid this file calls. */
export type MermaidApi = {
  initialize(config: Record<string, unknown>): void;
  render(id: string, source: string): Promise<{ svg: string }>;
};

/** The house token names a diagram's colours are read from, and the Mermaid theme variable each one sets. */
const TOKEN_FOR: Record<string, string> = {
  background: '--ink-1', mainBkg: '--ink-3', nodeBorder: '--line-hi', lineColor: '--text-2', textColor: '--text',
  primaryColor: '--ink-3', primaryBorderColor: '--blue', primaryTextColor: '--text',
  secondaryColor: '--ink-4', tertiaryColor: '--ink-2', noteBkgColor: '--ink-4', noteTextColor: '--text',
  clusterBkg: '--ink-2', clusterBorder: '--line-hi', edgeLabelBackground: '--ink-2', titleColor: '--text',
  actorBkg: '--ink-3', actorBorder: '--blue', actorTextColor: '--text', actorLineColor: '--line-hi',
  signalColor: '--text-2', signalTextColor: '--text', labelBoxBkgColor: '--ink-3', labelBoxBorderColor: '--line-hi',
  labelTextColor: '--text', loopTextColor: '--text', activationBkgColor: '--ink-4', sequenceNumberColor: '--ink-0',
  pieTitleTextColor: '--text', pieSectionTextColor: '--ink-0', pieLegendTextColor: '--text',
  pieStrokeColor: '--ink-1', pieOuterStrokeColor: '--line-hi',
};

/** Pie slices and chart series, in order, from the house colours that carry no meaning of their own. */
const SERIES = ['--blue', '--k-routine', '--k-plan', '--brass', '--k-person', '--k-diet', '--k-home', '--cyan', '--k-health', '--ok', '--k-preference', '--k-other'];

/** Mermaid's theme variables from the page's tokens; `read` gives a token's value (empty for one the page lacks, which is left out). */
export function themeVariables(read: (token: string) => string): Record<string, string | boolean> {
  const vars: Record<string, string | boolean> = { darkMode: true, fontFamily: read('--f-body') || 'sans-serif' };
  for (const [name, token] of Object.entries(TOKEN_FOR)) {
    const value = read(token).trim();
    if (value) vars[name] = value;
  }
  SERIES.forEach((token, i) => {
    const value = read(token).trim();
    if (value) vars[`pie${i + 1}`] = value;
  });
  return vars;
}

/** What Mermaid's `strict` level leaves out: no click callbacks and no HTML in labels. */
export function configFor(vars: Record<string, string | boolean>): Record<string, unknown> {
  return {
    startOnLoad: false, suppressErrorRendering: true, securityLevel: 'strict', theme: 'base', themeVariables: vars,
    htmlLabels: false, flowchart: { htmlLabels: false }, deterministicIds: true,
  };
}

/** A parse failure's message as Mermaid wrote it, with the markup its error diagram would carry left out. */
export function messageOf(error: unknown): string {
  const text = error instanceof Error ? error.message : String(error);
  return text.replace(/<[^>]*>/g, '').trim() || 'Mermaid could not read this diagram.';
}

let queue: Promise<unknown> = Promise.resolve();
let counter = 0;

/** Draws `source`, one at a time (Mermaid keeps one global config and measures in a scratch element). */
export function draw(mermaid: MermaidApi, source: string, vars: Record<string, string | boolean>): Promise<Drawn> {
  const run = async (): Promise<Drawn> => {
    const id = `diagram-${++counter}`;
    try {
      mermaid.initialize(configFor(vars));
      const { svg } = await mermaid.render(id, source);
      return { is: 'svg', svg };
    } catch (e) {
      return { is: 'error', message: messageOf(e) };
    } finally {
      document.getElementById(`d${id}`)?.remove();
    }
  };
  const next = queue.then(run, run);
  queue = next;
  return next;
}

let loaded: Promise<MermaidApi> | null = null;

/** Mermaid itself, loaded once. */
export function loadMermaid(): Promise<MermaidApi> {
  loaded ??= import('mermaid').then((m) => m.default);
  return loaded;
}
