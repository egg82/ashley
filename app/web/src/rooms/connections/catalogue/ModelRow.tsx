// One model as the catalogue holds it: its name, its price word, and each figure under its label. A figure the catalogue
// does not hold is drawn as unknown.
import type { ComponentChildren } from 'preact';
import type { ModelCatalogueModel } from '../../../api/types';
import { perMtok, priceWord, tokenCount, yesNo } from './format';

function Cell({ label, value, unit }: { label: string; value: string | null; unit?: string }) {
  return (
    <div class="cc-cell">
      <dt class="meta">{label}</dt>
      <dd>{value === null ? <span class="unk" role="img" aria-label="not known" /> : <>{value}{unit && <span class="meta"> {unit}</span>}</>}</dd>
    </div>
  );
}

function Pill({ children, why }: { children: ComponentChildren; why?: string }) {
  return <span class="pill cc-pill" title={why}>{children}</span>;
}

export function ModelRow({ model }: { model: ModelCatalogueModel }) {
  const f = model.fields;
  const word = priceWord(model.price.status);
  const edited = model.overrides.map((o) => o.field_name);
  return (
    <li class="cc-model">
      <div class="cc-name">
        <span class="cc-title">{f.name ?? model.model}</span>
        {f.name !== null && f.name !== model.model && <span class="meta cc-id">{model.model}</span>}
        <span class="cc-tags">
          {word && <Pill>{word}</Pill>}
          {f.hidden === true && <Pill>hidden</Pill>}
          {f.tiers.length > 0 && <Pill why="Longer prompts pay other prices">tiered</Pill>}
          {edited.length > 0 && <Pill why={edited.join(', ')}>{edited.length} edited</Pill>}
        </span>
      </div>
      <dl class="cc-cells">
        <Cell label="Input" value={perMtok(f.input_usd_per_mtok)} unit="/ M" />
        <Cell label="Output" value={perMtok(f.output_usd_per_mtok)} unit="/ M" />
        <Cell label="Cache read" value={perMtok(f.cache_read_usd_per_mtok)} unit="/ M" />
        <Cell label="Cache write" value={perMtok(f.cache_write_usd_per_mtok)} unit="/ M" />
        <Cell label="Context" value={tokenCount(f.context_tokens)} unit="tokens" />
        <Cell label="Max output" value={tokenCount(f.max_output_tokens)} unit="tokens" />
        <Cell label="Tools" value={yesNo(f.tool_call)} />
        <Cell label="Structured" value={yesNo(f.structured_output)} />
      </dl>
    </li>
  );
}
