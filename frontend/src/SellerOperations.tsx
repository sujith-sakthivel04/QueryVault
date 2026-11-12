import React, { Suspense, lazy, useMemo, useState } from 'react';
import { money } from './api';
import { Session, verifiedCaptureCents } from './presentation';
const SellerLedger = lazy(() => import('./SellerLedger'));

type LedgerEvent = Record<string, unknown> & {
  event?: string;
  quote_id?: string;
  id?: number;
  cents?: number;
  created_at?: string;
};

const shortQuoteId = (value: unknown) => String(value || '').slice(0, 8);
const formatLedgerTime = (value: unknown) => {
  const exact = String(value || '');
  const date = new Date(exact);
  if (Number.isNaN(date.valueOf())) return exact || 'Unknown time';
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date);
};

export default function SellerOperations({ evaluation, catalogue, ledger, active }: {
  evaluation: any;
  catalogue: any;
  ledger: LedgerEvent[];
  active?: Session;
}) {
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState<LedgerEvent>();
  const fullQuoteIds = [...new Set(ledger.map((row) => row.quote_id).filter((id): id is string => typeof id === 'string' && id.length > 0))];
  const captured = active?.state === 'settled' ? verifiedCaptureCents(active) : null;
  const charged = ledger.filter((row) => row.event === 'charged');
  const chargedCents = charged.reduce((total, row) => total + Number(row.cents || 0), 0);
  const quoteComparisons = useMemo(() => charged.map((charge) => ({
    charge,
    quote: ledger.find((row) => row.event === 'quoted' && row.quote_id === charge.quote_id),
  })), [charged, ledger]);

  return (
    <div className="seller-workspace">
      <section className="panel seller-reconciliation" aria-labelledby="seller-reconciliation-title">
        <div className="panelhead">
          <div><h2 id="seller-reconciliation-title">Recorded usage to verified collection</h2></div>
          <span className="badge session-state">{active?.state || 'No session'}</span>
        </div>
        <div className="reconciliation-flow" aria-label="Financial reconciliation from query charges to payment collection">
          <div className="reconciliation-node">
            <span>Recorded query charges</span>
            <strong>{money(chargedCents)}</strong>
            <small>{charged.length} charged {charged.length === 1 ? 'query' : 'queries'} in this ledger</small>
          </div>
          <div className="reconciliation-link" aria-hidden="true"></div>
          <div className="reconciliation-node collection-node">
            <span>Independently verified collection</span>
            <strong>{captured !== null ? money(captured) : 'Not verified'}</strong>
            <small>{captured === null ? 'Only a verified completed capture appears here' : captured === chargedCents ? 'Completed capture equals recorded query charges' : 'Capture matches session spend; ledger totals differ and need review'}</small>
          </div>
        </div>
        <div className="reservation-note"><span>Internal reservations</span><strong>{money(active?.reserved || 0)}</strong><small>Held inside the query workflow; not a PayPal collection.</small></div>
        <p className="fine">Accrued usage, independently verified collection, and internal reservations are separate records. A quote is not a charge and a reservation is not a payment.</p>

        <div className="quote-reconciliation">
          <div className="panelhead"><div><h3>Quoted amount and recorded charge</h3></div></div>
          {quoteComparisons.length ? (
            <div className="quote-match-list">
              {quoteComparisons.map(({ charge, quote }) => (
                <div className="quote-match-row" key={charge.id}>
                  <span className="quote-match-id">{shortQuoteId(charge.quote_id)}</span>
                  <span><small>Quoted</small><strong>{typeof quote?.cents === 'number' ? money(quote.cents) : 'No quote record'}</strong></span>
                  <span><small>Charged</small><strong>{money(Number(charge.cents || 0))}</strong></span>
                </div>
              ))}
            </div>
          ) : <p>No completed query charges in this session.</p>}
        </div>
      </section>

      <section className="panel seller-ledger-panel" aria-labelledby="seller-ledger-title">
        <div className="panelhead">
          <div><span className="eyebrow">Append-only ledger</span><h2 id="seller-ledger-title">Transaction ledger</h2></div>
          <span className="badge">{ledger.filter((row) => row.event === 'security_rejection').length} policy rejections</span>
        </div>
        <label htmlFor="seller-ledger-search">Search ledger events</label>
        <input id="seller-ledger-search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Event, quote ID, or amount" />
        <p className="seller-grid-hint">Select a row to inspect its full quote ID and exact timestamp.</p>
        <Suspense fallback={<p role="status">Loading audited ledger…</p>}>
          <SellerLedger ledger={ledger} filter={filter} selectedId={selected?.id} onSelect={setSelected} />
        </Suspense>
        <section className="ledger-evidence" aria-labelledby="ledger-evidence-title" aria-live="polite">
          <div className="panelhead"><div><span className="eyebrow">Selected record</span><h3 id="ledger-evidence-title">Supporting evidence</h3></div></div>
          {selected ? (
            <>
              <dl className="ledger-evidence-grid">
                <div><dt>Event</dt><dd>{String(selected.event || 'Unknown event').replaceAll('_', ' ')}</dd></div>
                <div><dt>Amount</dt><dd>{typeof selected.cents === 'number' ? money(selected.cents) : 'Not applicable'}</dd></div>
                <div><dt>Quote</dt><dd>{selected.quote_id ? shortQuoteId(selected.quote_id) : 'No quote linked'}</dd></div>
                <div><dt>Recorded</dt><dd><time dateTime={String(selected.created_at || '')}>{formatLedgerTime(selected.created_at)}</time></dd></div>
              </dl>
              <details><summary>Inspect complete ledger event</summary><pre>{JSON.stringify(selected, null, 2)}</pre></details>
            </>
          ) : <p className="fine">Select a ledger row to inspect the exact recorded event and supporting identifiers.</p>}
        </section>
        {fullQuoteIds.length > 0 && <details className="full-quote-identifiers"><summary>Full quote identifiers · {fullQuoteIds.length}</summary><ul>{fullQuoteIds.map((id) => <li key={id}><span>{shortQuoteId(id)}</span><code>{id}</code></li>)}</ul></details>}
        <p className="fine">The ledger retains exact event timestamps for sorting and accessible inspection. Charges are recorded usage; revenue appears only after independent settlement verification.</p>
      </section>

      <details className="seller-supporting-data">
        <summary>Evaluation and dataset evidence</summary>
        <section className="panel catalogue">
          <h2>Reproducible local evaluation</h2>
          <p>{evaluation?.legitimate_accepted ?? '—'} legitimate accepted · {evaluation?.security_rejections ?? '—'} attacks rejected · {evaluation?.known_answers_correct ?? '—'} known answers correct</p>
          {evaluation?.live_ai_correctness && <p>Recorded live AI evaluation: {evaluation.live_ai_correctness.correct}/{evaluation.live_ai_correctness.attempted} known answers · non-billing evaluation record</p>}
          <p className="muted">These saved evaluation figures do not cause a new model request.</p>
        </section>
        <section className="panel catalogue">
          <h2>Dataset catalogue</h2><p>{catalogue?.provenance}</p><p className="muted">{catalogue?.policy}</p>
          {Object.entries(catalogue?.schema?.vault_data || {}).map(([name, columns]) => <details key={name}><summary>{name}</summary><pre>{JSON.stringify(columns, null, 2)}</pre></details>)}
        </section>
      </details>
    </div>
  );
}
