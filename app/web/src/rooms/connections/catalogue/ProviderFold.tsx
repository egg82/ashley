// One provider: a fold whose summary says who it is and whether the deployment is connected to it, and whose body reads
// its models the first time it opens.
import { useState } from 'preact/hooks';
import type { ModelCatalogueProvider } from '../../../api/types';
import { SHOWN } from './format';
import { ModelRow } from './ModelRow';
import { listings, loadModels } from './state';

function Connected({ value }: { value: boolean | null }) {
  if (value === null) return <span class="unk" role="img" aria-label="connection not known" />;
  return value ? <span class="pill cc-connected">connected</span> : <span class="meta">not connected</span>;
}

function Models({ provider }: { provider: ModelCatalogueProvider }) {
  const [all, setAll] = useState(false);
  const listing = listings.value[provider.provider];
  if (listing === undefined || listing === 'loading') return <p class="meta cc-note">Reading the models…</p>;
  if (listing === 'failed') {
    return (
      <p class="cc-note">
        <span class="unk">couldn’t read these models</span>{' '}
        <button class="btn sm ghost" type="button" onClick={() => void loadModels(provider.provider)}>Try again</button>
      </p>
    );
  }
  if (listing.length === 0) return <p class="meta cc-note">The catalogue lists no models for this provider.</p>;
  const shown = all ? listing : listing.slice(0, SHOWN);
  return (
    <>
      <ul class="cc-models">{shown.map((m) => <ModelRow key={m.model} model={m} />)}</ul>
      {shown.length < listing.length && (
        <button class="btn sm ghost cc-more" type="button" onClick={() => setAll(true)}>Show all {listing.length} models</button>
      )}
    </>
  );
}

export function ProviderFold({ provider }: { provider: ModelCatalogueProvider }) {
  return (
    <details class="cc-provider" onToggle={(e) => { if (e.currentTarget.open) void loadModels(provider.provider); }}>
      <summary>
        <span class="cc-pname">{provider.name}</span>
        <span class="meta cc-pid">{provider.provider}</span>
        <span class="cc-pfacts">
          <span class="meta">{provider.model_count} {provider.model_count === 1 ? 'model' : 'models'}</span>
          {provider.overridden_count > 0 && <span class="meta">{provider.overridden_count} edited</span>}
          <Connected value={provider.has_connection} />
        </span>
      </summary>
      <div class="cc-body"><Models provider={provider} /></div>
    </details>
  );
}
