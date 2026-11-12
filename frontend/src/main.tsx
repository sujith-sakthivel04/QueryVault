import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, money } from './api';
import DecisionTimeline from './DecisionTimeline';
import ProofEngine, { ProofEvidence } from './ProofEngine';
import SessionStatus from './SessionStatus';
import { Session, sessionView } from './presentation';
import { Runtime, isPublicMode, previewBody, workspaceTab } from './runtime';
import InteractiveResearch from './InteractiveResearch';
import SellerOperations from './SellerOperations';
import './style.css';

const researchExamples = [
  'Which ports had the highest average shipment delay in October 2026?',
  'How many shipments occurred in October 2026?',
  'What is the average container count by port?',
  'Which routes experienced the longest delays?',
];

function formatResultValue(value: unknown) {
  const exact = String(value);
  const numeric = (typeof value === 'number' && Number.isFinite(value)) ||
    (typeof value === 'string' && /^-?\d+(?:\.\d+)?$/.test(value));
  if (!numeric) return { display: exact, exact, changed: false };
  const number = Number(value);
  const display = Number.isInteger(number)
    ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(number)
    : new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(number);
  return { display, exact, changed: display !== exact };
}

function BrandLockup() {
  return <img className="brand-logo" src="/brand/queryvault-horizontal-dark.svg" alt="" width="248" height="48" />;
}

function App() {
  const [runtime, setRuntime] = useState<Runtime>();
  const runtimeRef = useRef<Runtime>({ mode: 'local' });
  const publicDemo = runtime?.mode === 'public_demo';
  const publicInteractive = runtime?.mode === 'public_interactive';
  const [tab, setTab] = useState(() => workspaceTab(window.location.pathname));
  const [health, setHealth] = useState<any>();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [active, setActive] = useState<Session>();
  const [ledger, setLedger] = useState<any[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [catalogue, setCatalogue] = useState<any>();
  const [evaluation, setEvaluation] = useState<any>();
  const [demo, setDemo] = useState<any>();
  const [sql, setSql] = useState('SELECT p.name, ROUND(AVG(s.delay_hours), 2) AS average_delay_hours\nFROM shipments s JOIN ports p ON s.port_id = p.id\nGROUP BY p.name ORDER BY average_delay_hours DESC');
  const [objective, setObjective] = useState('Which ports had the highest average shipment delay in October 2026?');
  const [quote, setQuote] = useState<any>();
  const [result, setResult] = useState<any>();
  const [agent, setAgent] = useState<any>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  async function refresh(sid?: string, restoreResults = false) {
    const [nextHealth, all] = await Promise.all([
      api('/health'),
      isPublicMode(runtimeRef.current) ? Promise.resolve([]) : api('/sessions'),
    ]);
    const preferred = sid || active?.id || localStorage.getItem('qv.session');
    const id = all.some((item: Session) => item.id === preferred) ? preferred : all[all.length - 1]?.id;
    const [nextActive, nextLedger, queries, nextRuns] = id
      ? await Promise.all([
          api('/sessions/' + id),
          api('/sessions/' + id + '/ledger'),
          api('/sessions/' + id + '/queries'),
          api('/sessions/' + id + '/agent-runs'),
        ])
      : [undefined, [], [], []];

    // Keep each session and its supporting evidence together when refreshing.
    setHealth(nextHealth);
    setSessions(all);
    setActive(nextActive);
    setLedger(nextLedger);
    setHistory(queries);
    setRuns(nextRuns);
    if (id) localStorage.setItem('qv.session', id);
    else localStorage.removeItem('qv.session');

    if (restoreResults) {
      const saved = queries.find((query: any) => query.state === 'completed' && query.result);
      setResult(saved ? { ...saved.result, recorded: true } : undefined);
      if (saved) setSql(saved.sql);
      setAgent(undefined);
      setQuote(undefined);
    }
  }

  async function action(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError('');
    try {
      await fn();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy('');
    }
  }

  useEffect(() => {
    void action('Connecting', async () => {
      const config = await api('/api/config');
      setRuntime(config);
      runtimeRef.current = config;
      if (!isPublicMode(config)) {
        await api('/api/local-login', {});
      } else if (config.preview) {
        setSql(config.preview.sql);
      }
      if (config.mode === 'public_interactive' || config.mode === 'public_demo') {
        setTab('buyer');
        window.history.replaceState(null, '', '/');
      }
      setCatalogue(await api('/catalogue'));
      setEvaluation(await api('/evaluation'));
      setDemo(await api('/demo/evidence'));
      await refresh(undefined, true);
    });
  }, []);

  function navigate(next: string) {
    if (publicDemo && next === 'seller') return;
    setTab(next);
    window.history.replaceState(null, '', next === 'seller' ? '/seller' : '/');
  }

  const currentTab = publicDemo ? 'buyer' : tab;
  const open = !publicDemo && active && ['authorized', 'active'].includes(active.state);
  const view = sessionView(active);
  const savedRecord = view.closed;
  const shownAgent = agent || runs[0]?.result;
  const historicalInspection = agent?.mode === 'historical_verified' || !!result?.historical;

  const lastDecision = shownAgent?.decisions?.[shownAgent.decisions.length - 1];
  const proofQuote = quote || shownAgent?.quote || (lastDecision?.quote_id ? {
    id: lastDecision.quote_id,
    price_cents: lastDecision.price_cents,
  } : undefined);
  const proofHasResult = !!(result?.rows || shownAgent?.result?.rows);
  const proofUsesFreePreview = !!result?.mode;
  const proofComplete = proofHasResult && !proofUsesFreePreview;
  const proofStopped = !!shownAgent?.requires_approval || !!shownAgent?.refused ||
    (!!error && !proofHasResult) || shownAgent?.mode === 'offline';
  let proofStage = 0;
  if (busy === 'Planning research') proofStage = 1;
  else if (busy === 'Executing quoted SQL') proofStage = 5;
  else if (shownAgent?.requires_approval || shownAgent?.attempts?.some((attempt: any) => attempt.outcome === 'rejected')) proofStage = 2;
  else if (shownAgent?.refused) proofStage = shownAgent.decisions?.length ? 3 : 1;
  else if (shownAgent?.mode === 'offline' || error) proofStage = 1;
  else if (proofComplete) proofStage = 6;
  else if (proofQuote) proofStage = 4;
  else if (shownAgent?.decisions?.length) proofStage = 3;

  const proofEvidence: ProofEvidence = {};
  if (objective) proofEvidence.Question = <p className="proof-copy">{objective}</p>;
  if (shownAgent) {
    proofEvidence.Proposal = (
      <div className="proof-stack">
        {lastDecision?.reason && <p>{lastDecision.reason}</p>}
        {shownAgent.message && <p>{shownAgent.message}</p>}
        {!lastDecision?.reason && !shownAgent.message && <p>No proposal detail was returned with this record.</p>}
        {lastDecision?.sql && <details><summary>Inspect proposed SQL</summary><pre>{lastDecision.sql}</pre></details>}
      </div>
    );
  }
  if (proofQuote) {
    proofEvidence.Validation = (
      <div className="proof-stack">
        <strong>{proofQuote.plan ? 'Read-only quote and PostgreSQL plan returned' : 'Quote record returned after SQL policy and planning'}</strong>
        <p>The backend returns a quote record only after the SQL policy and planning checks succeed.</p>
        {proofQuote.plan && <pre>{JSON.stringify(proofQuote.plan, null, 2)}</pre>}
      </div>
    );
    proofEvidence.Quote = (
      <div className="proof-stack proof-numbers">
        <strong>{money(typeof proofQuote.price === 'number' ? proofQuote.price : proofQuote.price_cents)}</strong>
        <p>Quote version {proofQuote.version || 'recorded'} · expires {proofQuote.expires_at ? new Date(proofQuote.expires_at).toLocaleTimeString() : 'not provided'}.</p>
        {proofQuote.id && <span>Quote ID · {proofQuote.id}</span>}
        {proofQuote.sql_hash && <span>SQL SHA-256 · {proofQuote.sql_hash}</span>}
      </div>
    );
  } else if (shownAgent?.requires_approval) {
    proofEvidence.Validation = <p className="proof-copy">{shownAgent.message || 'The recorded proposal requires scope review. No query execution followed.'}</p>;
  }
  const manualQuoteAcceptance = busy === 'Executing quoted SQL' ||
    (!!proofQuote?.id && result?.quote_id === proofQuote.id && !shownAgent?.result);
  if (manualQuoteAcceptance) {
    proofEvidence.Acceptance = (
      <div className="proof-stack">
        <strong>Explicit quote action</strong>
        <p>The execution request is bound to the returned quote ID, SQL fingerprint, and accepted maximum price.</p>
      </div>
    );
  } else if (shownAgent?.result) {
    proofEvidence.Acceptance = (
      <div className="proof-stack">
        <strong>Per-query acceptance is not recorded</strong>
        <p>The local agent path executes an affordable quote under the already-authorized session budget. The SQL workbench below provides explicit quote acceptance.</p>
      </div>
    );
  } else if (result?.recorded || result?.historical) {
    proofEvidence.Acceptance = <p className="proof-copy">This is a saved result. It does not record an acceptance action by the current viewer.</p>;
  }
  const executionResult = result?.rows ? result : shownAgent?.result;
  if (executionResult) {
    proofEvidence.Execution = (
      <div className="proof-stack">
        <strong>{executionResult.rows.length} rows returned</strong>
        <p>{executionResult.recorded || executionResult.historical ? 'Saved execution record.' : 'Database execution completed.'}</p>
      </div>
    );
    proofEvidence.Result = (
      <div className="proof-stack">
        <strong>{executionResult.rows.length} rows</strong>
        <p>Recorded query charge {money(executionResult.charged_cents || 0)}. Payment settlement is tracked separately.</p>
      </div>
    );
  }

  const historicalCard = currentTab === 'buyer' && demo && (
    <section className="panel historical" aria-labelledby="historical-title">
      <span className="eyebrow">HISTORICAL EVIDENCE · NOT A LIVE CHECKOUT · {demo.verified_date}</span>
      <h2 id="historical-title">Verified earlier: two answers, one {money(demo.captured_cents)} settlement.</h2>
      <p>Authorized {money(demo.authorized_cents)} → queries {money(demo.queries[0].price_cents)} + {money(demo.queries[1].price_cents)} → independently confirmed {demo.capture_status} capture {money(demo.captured_cents)}. Ledger difference {money(demo.ledger_difference_cents)}.</p>
      <p className="evidence-note">Viewing recorded evidence only. Inspecting it does not start a checkout, model request, query execution, or payment.</p>
      <button disabled={!!busy} onClick={() => {
        setQuote(undefined);
        setSql(demo.queries[0].sql);
        setResult({ rows: demo.queries[0].rows, charged_cents: demo.queries[0].price_cents, historical: true });
        setAgent({
          mode: 'historical_verified',
          decisions: [{
            reason: demo.queries[0].decision,
            price_cents: demo.queries[0].price_cents,
            remaining_cents: demo.queries[0].remaining_budget_cents,
            sql: demo.queries[0].sql,
          }],
          result: { rows: demo.queries[0].rows, charged_cents: demo.queries[0].price_cents },
        });
      }}>Inspect historical agent analysis</button>
    </section>
  );

  if (publicInteractive) {
    return (
      <div className="shell shell-public-interactive">
        <aside className="workspace-sidebar">
          <a className="brand" href="/" aria-label="QueryVault research desk"><BrandLockup /></a>
          <div className="sidebar-caption">THE PROOF ENGINE</div>
          <nav aria-label="Workspace"><span className="nav-current" aria-current="page">Research desk</span></nav>
          <div className="side-note"><span className="eyebrow">PUBLIC INTERACTIVE</span><p>Synthetic logistics data<br />Virtual allowance only</p></div>
          <div className="side-bottom">Evidence before<br />execution.</div>
        </aside>
        <main className="app-main">
          <header className="app-topbar">
            <div><span className="eyebrow">QUERYVAULT / RESEARCH</span><p className="muted">{new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</p></div>
            <span className="badge status-badge">{health?.database === 'connected' ? 'Database ready' : 'Checking database'}</span>
          </header>
          <section className="page-intro buyer-intro">
            <div><span className="eyebrow">LOGISTICS INTELLIGENCE · OCTOBER 2026</span><h1>Research with the proof attached.</h1></div>
            <p>Ask a bounded question. Inspect its evidence. Accept the exact quote before a query runs.</p>
          </section>
          {error && <div role="alert" className="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
          {busy && <div role="status" className="loading">{busy}…</div>}
          <div className="interactive-mode-banner"><strong>Public interactive demo</strong><span>Synthetic read-only data · non-billing virtual allowance · no PayPal payment</span></div>
          <InteractiveResearch />
          {demo && <section className="panel historical historical-secondary">
            <span className="eyebrow">SEPARATE HISTORICAL RECORD · {demo.verified_date}</span>
            <h2>Earlier verified capture · {money(demo.captured_cents)}</h2>
            <p>Authorized {money(demo.authorized_cents)} → independently verified {demo.capture_status} capture {money(demo.captured_cents)}. This historical PayPal record is separate from today’s virtual demo allowance.</p>
            <p className="evidence-note">No payment or financial ledger entry is created in public interactive mode.</p>
          </section>}
          <footer><span>QUERYVAULT · PUBLIC INTERACTIVE RESEARCH</span><span>Virtual allowance · no real payment</span></footer>
        </main>
      </div>
    );
  }

  return (
    <div className={currentTab === 'seller' ? 'shell shell-seller' : 'shell'}>
      <aside className="workspace-sidebar">
        <a className="brand" href="/" aria-label="QueryVault research desk"><BrandLockup /></a>
        <div className="sidebar-caption">THE PROOF ENGINE</div>
        <nav aria-label="Workspace">
          <button className={currentTab === 'buyer' ? 'selected' : ''} onClick={() => navigate('buyer')}>Research desk</button>
          {!publicDemo && <button className={currentTab === 'seller' ? 'selected' : ''} onClick={() => navigate('seller')}>Seller operations</button>}
        </nav>
        <div className="side-note">
          <span className="eyebrow">{publicDemo ? 'RESTRICTED PUBLIC DEMO' : 'LOCAL OPERATOR WORKSPACE'}</span>
          <p>{publicDemo ? 'Fixed synthetic previews' : 'PayPal Sandbox · single operator'}</p>
        </div>
        <div className="side-bottom">Clear questions.<br />Verifiable answers.</div>
      </aside>

      <main className="app-main">
        <header className="app-topbar">
          <div><span className="eyebrow">QUERYVAULT / {currentTab === 'buyer' ? 'BUYER' : 'SELLER'}</span><p className="muted">{new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })} · Logistics intelligence</p></div>
          <span className="badge status-badge">{health?.database === 'connected' ? 'Database ready' : 'Checking database'}</span>
        </header>

        {currentTab === 'seller' ? (
          <>
            <section className="page-intro seller-intro">
              <div><span className="eyebrow">FINANCIAL OPERATIONS · LOCAL ONLY</span><h1>Every query accounted for.</h1></div>
              <p>Reconcile recorded usage against verified collection and inspect each ledger event.</p>
            </section>
            {error && <div role="alert" className="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
            {busy && <div role="status" className="loading">{busy}…</div>}
            <SellerOperations evaluation={evaluation} catalogue={catalogue} ledger={ledger} active={active} />
          </>
        ) : (
          <>
            <section className="page-intro buyer-intro">
              <div><span className="eyebrow">{publicDemo ? 'RESTRICTED LOGISTICS PREVIEW' : 'LOGISTICS INTELLIGENCE · OCTOBER 2026'}</span><h1>{publicDemo ? 'Explore the evidence.' : 'Research with the proof attached.'}</h1></div>
              <p>{publicDemo ? 'Inspect a fixed, read-only synthetic query. AI planning, checkout, and operator data are unavailable in this mode.' : 'A question becomes a validated, priced decision before it reaches the database.'}</p>
            </section>

            {error && <div role="alert" className="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
            {busy && <div role="status" className="loading">{busy}…</div>}

            {!publicDemo ? (
              <>
                <section className="sessionbar" aria-label="Research session controls">
                  <label htmlFor="research-session">Research session
                    <select id="research-session" disabled={!!busy} value={active?.id || ''} onChange={(event) => void action('Loading session', async () => {
                      setQuote(undefined); setResult(undefined); setAgent(undefined);
                      if (!event.target.value) {
                        setActive(undefined); setHistory([]); setRuns([]); setLedger([]);
                        localStorage.removeItem('qv.session');
                        return;
                      }
                      await refresh(event.target.value, true);
                    })}>
                      <option value="">Select a session</option>
                      {sessions.map((session) => <option key={session.id} value={session.id}>{session.id.slice(0, 8)} · {session.state}</option>)}
                    </select>
                  </label>
                  <span className="badge session-state">{active?.state || 'No active session'}</span>
                  <button className="secondary" disabled={!!busy} onClick={() => void action('Refreshing', () => refresh(undefined, true))}>Refresh records</button>
                  <details className="live-operations"><summary>New Sandbox checkout</summary><p>Starts a separate $20 Sandbox order and requires fresh human approval. Saved evidence inspection never creates an order.</p><button disabled={!!busy || !health || health?.paypal === 'credentials_missing'} onClick={() => void action('Creating Sandbox order', async () => {
                    const session = await api('/sessions', {});
                    setAgent(undefined); setResult(undefined);
                    await refresh(session.id, true);
                  })}>Create new $20 Sandbox order</button></details>
                </section>
              </>
            ) : (
              <section className="public-capability" aria-label="Restricted public demo capabilities">
                <strong>Fixed preview only</strong>
                <span>No live AI · no checkout · no operator sessions · no arbitrary SQL</span>
              </section>
            )}

            <div className="workspace buyer-workspace">
              <section className="panel research-panel" aria-labelledby="research-brief-title">
                {publicDemo ? (
                  <>
                    <div className="panelhead"><div><span className="eyebrow">READ-ONLY RESEARCH</span><h2 id="research-brief-title">Fixed logistics preview</h2></div><span className="badge">NO AI · NO PAYMENT</span></div>
                    <p className="muted">This preset query is validated by the restricted backend and runs against synthetic data.</p>
                    <label htmlFor="preview-sql">Preset SQL · read-only</label>
                    <textarea className="sql" id="preview-sql" value={sql} readOnly spellCheck={false} />
                    <button disabled={!!busy} onClick={() => void action('Running fixed preview', async () => {
                      const next = await api('/demo/query', previewBody(runtime, sql));
                      setResult(next); setQuote(undefined);
                    })}>Run fixed logistics preview</button>
                  </>
                ) : (
                  <>
                    <div className="panelhead"><div><h2 id="research-brief-title">Start with a question</h2></div><span className="badge">{savedRecord ? 'SAVED SESSION' : health?.ai === 'offline' ? 'AI OFFLINE' : busy === 'Planning research' ? 'REQUEST RUNNING' : 'LOCAL OPERATOR'}</span></div>
                    <p className="muted">Choose an example to edit it, or write a research question. Nothing runs until you request it.</p>
                    <label htmlFor="objective">Your research question</label>
                    <textarea disabled={!!busy} id="objective" value={objective} onChange={(event) => setObjective(event.target.value)} maxLength={500} />
                    <div className="prompt-examples" aria-label="Research examples">
                      {researchExamples.map((example) => <button type="button" className="prompt-example" key={example} disabled={!!busy} onClick={() => setObjective(example)}>{example}</button>)}
                    </div>
                    <div className="research-action-row">
                      <button disabled={!open || !!busy} onClick={() => void action('Planning research', async () => {
                        setAgent(undefined); setResult(undefined); setQuote(undefined);
                        const nextAgent = await api('/agent', { session_id: active!.id, objective });
                        setAgent(nextAgent);
                        if (nextAgent.result) setResult(nextAgent.result);
                        await refresh();
                        if (nextAgent.quote) { setQuote(nextAgent.quote); setSql(nextAgent.quote.sql); }
                      })}>Generate priced plan</button>
                      <span>{open ? 'Local agent may execute an affordable quote within this authorized session.' : 'A locally authorized session is required for paid research.'}</span>
                    </div>
                  </>
                )}

                {!publicDemo && !result?.mode && (
                  <ProofEngine activeStage={proofStage} state={proofStopped ? 'Stopped without execution' : proofComplete ? 'Result recorded' : busy === 'Planning research' ? 'Planning proposal' : proofQuote ? 'Awaiting quote acceptance' : 'Ready for a question'} evidence={proofEvidence} stopped={proofStopped} complete={proofComplete} statusOverrides={shownAgent?.result && !manualQuoteAcceptance ? { Acceptance: 'No per-query record' } : result?.recorded || result?.historical ? { Acceptance: 'Historical only' } : {}} />
                )}
                {result?.mode && <div className="proof-bypass-note"><strong>Free preview path</strong><span>Read-only policy validation and a real result; no proposal, commercial quote, per-query acceptance, or session charge.</span></div>}

                {shownAgent && <DecisionTimeline record={shownAgent} historical={!agent || savedRecord || shownAgent.mode === 'historical_verified'} />}
                {runs.length > 0 && <details className="saved-decisions"><summary>Saved decision records · {runs.length}</summary>{runs.map((run) => <article key={run.id}><p>{run.objective} · {run.state}</p><DecisionTimeline record={run.result} error={run.error} historical /></article>)}</details>}

                {!publicDemo && <>
                  <hr />
                  <div className="panelhead"><div><h2>SQL proposal and quote</h2></div></div>
                  <label htmlFor="sql">Read-only SQL · edits clear the current quote and result</label>
                  <textarea disabled={!!busy} className="sql" id="sql" value={sql} spellCheck={false} onChange={(event) => {
                    setSql(event.target.value); setQuote(undefined); setResult(undefined);
                  }} />
                  <div className="actions">
                    <button className="secondary" disabled={!!busy} onClick={() => void action('Previewing synthetic data', async () => {
                      const next = await api('/demo/query', previewBody(runtime, sql));
                      setResult(next); setQuote(undefined);
                    })}>Free synthetic preview</button>
                    <button disabled={!open || !!busy} onClick={() => void action('Validating and pricing', async () => setQuote(await api('/quote', { session_id: active!.id, sql })))}>Validate and quote</button>
                    <button className="quiet-danger" disabled={!!busy} onClick={() => {
                      setResult(undefined); setSql("SELECT pg_read_file('/etc/passwd')"); setQuote(undefined);
                    }}>Load security test</button>
                  </div>
                  {quote && <div className="quote">
                    <div className="quote-heading"><div><span className="eyebrow">DETERMINISTIC QUOTE</span><strong>{money(quote.price)}</strong></div><span>{quote.version}</span></div>
                    <p>{quote.plan['Node Type']} · estimated planner cost {quote.plan['Total Cost']}<br />Maximum 100 rows · 2 seconds · expires {new Date(quote.expires_at).toLocaleTimeString()}</p>
                    <details><summary>Inspect quote binding</summary><dl><dt>SQL SHA-256</dt><dd>{quote.sql_hash}</dd><dt>Quote ID</dt><dd>{quote.id}</dd></dl></details>
                    <button disabled={!open || !!busy} onClick={() => void action('Executing quoted SQL', async () => {
                      setResult(await api('/execute', { quote_id: quote.id, max_price_cents: quote.price, sql_hash: quote.sql_hash }));
                      await refresh();
                    })}>Accept exact quote and execute · {money(quote.price)}</button>
                  </div>}
                </>}
              </section>

              <section className="panel finance-panel" aria-labelledby="finance-title">
                <div className="panelhead"><div>{publicDemo && <span className="eyebrow">RESTRICTED MODE</span>}<h2 id="finance-title">{publicDemo ? 'Demo boundary' : view.closed ? 'Verified session record' : historicalInspection && !active ? 'Historical payment record' : 'Authorization and settlement'}</h2></div></div>
                <p className="muted">{publicDemo ? 'Checkout and live AI are disabled. This mode only runs the fixed synthetic preview.' : historicalInspection && !active ? 'The evidence below belongs to an earlier verified session; no current checkout exists.' : view.closed ? 'This session is complete. The records below show saved verification state.' : health?.paypal === 'credentials_missing' ? 'No Sandbox credentials are configured. Live checkout is unavailable.' : 'A human approves the Sandbox budget before this session can authorize paid query work.'}</p>
                {active?.approval_url && active.state === 'awaiting_approval' && <>
                  <a className="button" href={active.approval_url} target="_blank" rel="noreferrer">Open PayPal Sandbox</a>
                  <button disabled={!!busy} onClick={() => void action('Verifying approval', async () => {
                    await api('/sessions/' + active.id + '/authorize', {}); await refresh();
                  })}>Verify approval and authorize</button>
                </>}
                <SessionStatus session={active} evidence={!active && historicalInspection ? demo : undefined} />
                {!publicDemo && (!historicalInspection || active) && <div className="receipt"><dl>
                  <dt>Order</dt><dd>{active?.order_id ? 'Private Sandbox reference' : 'Awaiting order'}</dd>
                  <dt>Authorization</dt><dd>{active?.authorization_id ? 'Private authorization reference' : 'Not authorized'}</dd>
                  <dt>Capture</dt><dd>{active?.capture_id ? 'Verified capture reference (private)' : 'Not captured'}</dd>
                </dl></div>}
                {view.canSettle && <button disabled={!!busy} onClick={() => void action('Settling session', async () => {
                  await api('/sessions/' + active!.id + '/settle', {}); await refresh();
                })}>Close session and settle {active ? money(active.spent) : ''}</button>}
                {!!active?.reserved && <button className="secondary" disabled={!!busy} onClick={() => void action('Recovering abandoned reservations', async () => {
                  await api('/sessions/' + active!.id + '/recover-queries', {}); await refresh();
                })}>Recover reservations older than 30 seconds</button>}
                {active?.error && <p role="alert" className="error">{active.error}</p>}
                {active?.state === 'reconciliation_required' && <button disabled={!!busy} onClick={() => void action('Reading PayPal status', async () => {
                  await api('/sessions/' + active.id + '/reconcile', {}); await refresh();
                })}>Recheck PayPal status</button>}
                {!!active?.payment && <details><summary>Payment verification record</summary><pre>{JSON.stringify({
                  status: (active.payment as any)?.status,
                  amount: (active.payment as any)?.amount,
                  final_capture: (active.payment as any)?.final_capture,
                }, null, 2)}</pre></details>}
                {!publicDemo && <p className="fine">One final capture. A zero-spend session voids the authorization. An authorization is not escrow or guaranteed payment.</p>}
                <hr />
                <div className="result-section">
                  <div className="panelhead"><div><h2>Query result</h2></div></div>
                  {history.length > 0 && <label htmlFor="saved-query">Saved query results
                    <select id="saved-query" disabled={!!busy} value={result?.quote_id || ''} onChange={(event) => {
                      const query = history.find((item: any) => item.id === event.target.value);
                      if (query) { setResult({ ...query.result, recorded: true }); setSql(query.sql); setQuote(undefined); }
                    }}>
                      <option value="">Select a completed query</option>
                      {history.filter((item: any) => item.state === 'completed').map((item: any) => <option key={item.id} value={item.id}>{item.id.slice(0, 8)} · {money(item.result?.charged_cents || 0)} · {item.result?.rows?.length || 0} rows</option>)}
                    </select>
                  </label>}
                  {result ? <>
                    <div className="result-meta">
                      <strong>{result.historical ? 'Historical verified query' : result.recorded ? 'Saved query' : result.mode ? 'Free synthetic preview' : 'Executed query'}</strong>
                      <span>{money(result.charged_cents)} · {result.rows.length} rows</span>
                    </div>
                    {result.rows.length === 1 ? (
                      <dl className="aggregate-result">{Object.entries(result.rows[0]).map(([key, value]) => {
                        const formatted = formatResultValue(value);
                        return <div key={key}><dt>{key}</dt><dd title={formatted.changed ? 'Exact value: ' + formatted.exact : undefined}>{formatted.display}</dd>{formatted.changed && <small>Exact value · {formatted.exact}</small>}</div>;
                      })}</dl>
                    ) : result.rows.length > 1 ? (
                      <div className="results"><table><thead><tr>{Object.keys(result.rows[0]).map((key: string) => <th scope="col" key={key}>{key}</th>)}</tr></thead><tbody>{result.rows.map((row: any, rowIndex: number) => <tr key={rowIndex}>{Object.entries(row).map(([key, value]) => {
                        const formatted = formatResultValue(value);
                        return <td key={key} className={typeof value === 'number' || /^-?\d+(?:\.\d+)?$/.test(String(value)) ? 'numeric-cell' : ''} title={formatted.changed ? 'Exact value: ' + formatted.exact : undefined}>{formatted.display}</td>;
                      })}</tr>)}</tbody></table></div>
                    ) : <p className="empty-result">The query returned no rows.</p>}
                    <details className="exact-results"><summary>Inspect exact SQL and returned values</summary><pre>{sql}</pre><pre>{JSON.stringify(result.rows, null, 2)}</pre></details>
                  </> : <div className="empty-result">No result recorded for this session.<span>Free previews do not charge the session. Paid execution requires an authorized session and a current quote.</span></div>}
                </div>
              </section>
              {historicalCard}
            </div>

            {!publicDemo && <>
              <section className="metrics financial-strip" aria-label="Current session accounting">
                {[
                  ['Session limit', active ? money(active.budget) : '—'],
                  [view.budgetLabel, view.budgetValue !== null ? money(view.budgetValue) : '—'],
                  ['Internal reservations', active ? money(active.reserved) : '—'],
                  ['Recorded query charges', active ? money(active.spent) : '—'],
                ].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
              </section>
              <p className="metric-context">{view.closed ? 'Unspent session budget is an accounting value. It does not confirm PayPal hold release, refunds, or funding-source availability.' : 'Query reservations are internal budget allocations, separate from any PayPal funding hold.'}</p>
              <div className={savedRecord ? 'operation-context saved' : 'operation-context'} role="status">
                <strong>{savedRecord ? 'Saved session · ' + view.title : historicalInspection ? 'Historical evidence inspection' : 'Current operator session'}</strong>
                <span>{savedRecord ? 'These are saved query and payment verification records. No additional payment action is required.' : historicalInspection ? 'Read-only inspection of recorded evidence. Live operations require a separate explicit action.' : 'A model request or new checkout starts only when explicitly requested. The free preview does not charge this session.'}</span>
              </div>
            </>}
          </>
        )}
        <footer><span>QUERYVAULT · FINANCIAL INTELLIGENCE WITH TRACEABLE EVIDENCE</span><span>{publicDemo ? 'Fixed synthetic preview · no AI or checkout' : currentTab === 'seller' ? 'Append-only local ledger · verified collection' : 'Quotes precede paid query execution'}</span></footer>
      </main>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
