// The model catalogue as it stands, for an admin of the deployment: where the list came from and how old it is, then each
// provider with its models. Opened at `/connections/catalogue`; the search is `?q=`, so a reload or a shared link lands
// in the same place.
import { useLocation } from 'preact-iso';
import { useEffect } from 'preact/hooks';
import type { ModelCatalogueResponse } from '../../../api/types';
import { cadence, connectedCount, orderProviders, when } from './format';
import { ProviderFold } from './ProviderFold';
import { loadCatalogue, overview } from './state';

const WHY: Record<'denied' | 'unreachable' | 'failed', { head: string; line: string }> = {
  denied: { head: 'Only the deployment’s admins can read this.', line: 'The catalogue prices every call for every household, so it is kept to them.' },
  unreachable: { head: 'Can’t reach Ashley.', line: 'The catalogue isn’t known from here. Try again in a moment.' },
  failed: { head: 'The catalogue didn’t load.', line: 'Nothing was changed. Try again in a moment.' },
};

function Fact({ label, children }: { label: string; children: preact.ComponentChildren }) {
  return <div class="cc-fact"><dt class="meta">{label}</dt><dd>{children}</dd></div>;
}

const Unknown = () => <span class="unk" role="img" aria-label="not known" />;

function Sources({ c }: { c: ModelCatalogueResponse }) {
  const connected = connectedCount(c.catalogue_providers);
  return (
    <dl class="panel cc-facts">
      <Fact label="Last fetched">{c.fetched_at ? when(c.fetched_at) : <span class="meta">not yet; the built-in list is in use</span>}</Fact>
      <Fact label="Built-in list from">{c.snapshot_taken_at ? when(c.snapshot_taken_at) : <Unknown />}</Fact>
      <Fact label="Refreshed">{cadence(c.refresh_s)}</Fact>
      <Fact label="Providers">{c.catalogue_providers.length}</Fact>
      <Fact label="Connected">{connected === null ? <Unknown /> : connected}</Fact>
    </dl>
  );
}

function Providers({ c }: { c: ModelCatalogueResponse }) {
  const { query, path, route } = useLocation();
  const q = typeof query.q === 'string' ? query.q : '';
  const shown = orderProviders(c.catalogue_providers, q);
  return (
    <section class="cc-list" aria-label="Providers">
      <div class="cc-tools">
        <input class="cc-search" type="search" placeholder="Find a provider" aria-label="Find a provider" value={q}
          onInput={(e) => route(e.currentTarget.value ? `${path}?q=${encodeURIComponent(e.currentTarget.value)}` : path, true)} />
        <span class="meta" role="status">
          {q ? `${shown.length} of ${c.catalogue_providers.length} providers` : `${c.catalogue_providers.length} providers`}
        </span>
      </div>
      {shown.length === 0
        ? <p class="set-empty">{c.catalogue_providers.length === 0 ? 'The catalogue lists no providers.' : 'No provider matches that.'}</p>
        : <div class="panel cc-providers">{shown.map((p) => <ProviderFold key={p.provider} provider={p} />)}</div>}
      <p class="set-foot">Prices are USD per million tokens, as the catalogue lists them.</p>
    </section>
  );
}

function Body() {
  const o = overview.value;
  if (o.state === 'loading') return <p class="set-none meta">Reading the catalogue…</p>;
  if (o.state !== 'ready') {
    const why = WHY[o.state];
    return (
      <div class="rr-down" role="alert">
        <div class="rr-down-says">
          <h2>{why.head}</h2>
          <p>{why.line}</p>
          {o.state !== 'denied' && <button class="btn primary" type="button" onClick={() => void loadCatalogue()}>Try again</button>}
        </div>
      </div>
    );
  }
  return <><Sources c={o.catalogue} /><Providers c={o.catalogue} /></>;
}

export function CataloguePage() {
  useEffect(() => { void loadCatalogue(); }, []);
  return (
    <>
      <div class="set-head">
        <h1>Model catalogue</h1>
        <span class="set-dock" data-dock />
        <a class="btn sm ghost cn-back" href="/connections">Connections</a>
      </div>
      <div class="cn-body"><Body /></div>
    </>
  );
}
