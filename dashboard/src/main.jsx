import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

const money = n => typeof n === 'number' ? '$' + n.toLocaleString('en-US', {maximumFractionDigits: 2}) : '—';
const percent = n => typeof n === 'number' ? (n * 100).toFixed(1) + '%' : '—';
const short = id => id ? id.slice(3, 11) : '—';
function Badge({status}) {return <span className={'badge ' + status}><i/>{status}</span>}
function Json({value}) {return <pre className="json">{JSON.stringify(value, null, 2)}</pre>}
function Experiment({trace}) {
  const [feature, setFeature] = useState('context.liquidity');
  const [value, setValue] = useState('10000000');
  const [result, setResult] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function run(event) {
    event.preventDefault(); setError(''); setResult(null); setBusy(true);
    try {
      const number = Number(value);
      if (!value.trim() || !Number.isFinite(number)) throw new Error('Enter a finite numeric input.');
      const query = new URLSearchParams({adapter: 'deterministic', feature, value: JSON.stringify(number)});
      const response = await fetch('/api/traces/' + encodeURIComponent(trace.trace_id) + '/counterfactual?' + query);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Experiment unavailable.');
      setResult(data);
    } catch(e) {setError(e.message)} finally {setBusy(false)}
  }
  return <div className="tab-content"><div className="eyebrow">COUNTERFACTUAL DEBUGGING</div><h3>What input would have changed the financial decision?</h3><p>Change one recorded market input and compare the resulting proposal. The synthetic deterministic adapter must first reproduce the original decision.</p>
    <form className="experiment-form" onSubmit={run}><label>Market input<select value={feature} onChange={e => {setFeature(e.target.value); setResult(null)}}><option value="context.liquidity">Liquidity (USD)</option><option value="context.apy">APY (fraction, e.g. 0.05)</option><option value="context.price">Asset price (USD)</option><option value="context.oracle_age_seconds">Oracle age (seconds)</option></select></label><label>Alternative value<input type="number" step="any" required value={value} onChange={e => {setValue(e.target.value); setResult(null)}}/></label><button className="button" disabled={busy}>{busy ? 'Replaying…' : 'Test this input'}</button></form>
    <p>Recorded value: <code>{JSON.stringify(trace.context?.[feature.split('.')[1]]) ?? 'Not recorded'}</code></p>
    {error && <div role="alert" className="error">{error}</div>}
    {result && <><div className="experiment-verdict">{result.decision_changed ? 'Decision changes with this input' : 'Decision unchanged with this input'}</div><div className="experiment-comparison"><div><label>ORIGINAL PROPOSAL</label><Json value={result.original}/></div><div><label>COUNTERFACTUAL PROPOSAL</label><Json value={result.counterfactual}/></div></div><p className="footnote">{result.limitations}</p></>}
  </div>
}
function App() {
  const [traces, setTraces] = useState([]), [detail, setDetail] = useState(null);
  const [selected, setSelected] = useState(null), [tab, setTab] = useState('timeline');
  const [query, setQuery] = useState(''), [filter, setFilter] = useState('all');
  const [error, setError] = useState(''), [loading, setLoading] = useState(true);
  async function request(url) {const r = await fetch(url); if (!r.ok) throw new Error('Unable to load verified traces. Check the local collector and database integrity.'); return r.json()}
  async function refresh() {
    setError(''); setLoading(true);
    try {setTraces(await request('/api/traces'))} catch(e) {setError(e.message)} finally {setLoading(false)}
  }
  useEffect(() => {refresh()}, []);
  useEffect(() => {
    if (!selected) {setDetail(null); return}
    let active = true; setDetail(null); setError('');
    request('/api/traces/' + encodeURIComponent(selected)).then(data => {if (active) setDetail(data)}).catch(e => {if (active) setError(e.message)});
    return () => {active = false};
  }, [selected]);
  const visible = traces.filter(t => (filter === 'all' || t.status === filter) && `${t.id} ${t.agent} ${t.action}`.toLowerCase().includes(query.toLowerCase()));
  const rate = status => traces.length ? (100 * traces.filter(t => status.includes(t.status)).length / traces.length).toFixed(1) + '%' : '—';
  const trace = detail?.trace, report = detail?.analysis;
  return <div className="app">
    <aside><div className="brand"><div className="mark">t<span>f</span></div>TraceFi</div><div className="workspace"><span className="dot"/> Local workspace <small>SQLite collector</small></div>
      <div className="nav-label">DECISION PROVENANCE</div><button className="nav active" onClick={() => setSelected(null)}>⌘ <span>Financial decisions</span><span className="count">{traces.length}</span></button>
      <div className="aside-note"><div className="tiny-title">THE DECISION, IN CONTEXT</div><p>Observe.<br/>Reproduce.<br/>Compare.<br/>Diagnose.</p></div>
      <div className="aside-footer"><span className="dot"/> Local storage<br/><small>TraceFi v0.1 · Open source</small></div>
    </aside>
    <main><header><div><span className="crumb">Workspace</span><span className="slash">/</span><span>Financial decisions</span>{selected && <><span className="slash">/</span><code>{short(selected)}</code></>}</div><span className="local"><span className="dot"/> Local · read only</span></header>
      <div className="content"><div className="page-heading"><div className="eyebrow">FINANCIAL DECISION PROVENANCE</div><div className="heading-row"><div><h1>{selected ? 'Reconstruct the financial decision' : 'Why this financial decision?'}</h1><p>{selected ? 'Connect market state, portfolio, evidence and risk controls to the proposed action.' : 'Capture decision provenance. Attribute failures. Test what would have changed the action.'}</p></div><button className="button" onClick={selected ? () => setSelected(null) : refresh}>{selected ? '← All traces' : '↻ Refresh'}</button></div></div>
      {error && <div role="alert" className="error">{error}</div>}
      {!selected ? <>
        <div className="stats"><div><span>RECENT TRACES</span><strong>{traces.length.toLocaleString()}</strong><small>Up to 1,000 latest decisions</small></div><div><span>SUCCESS</span><strong>{rate(['success'])}</strong><small>Completed trace lifecycle</small></div><div><span>REJECTED</span><strong>{rate(['rejected'])}</strong><small>Blocked by recorded policy</small></div><div><span>FAILED</span><strong>{rate(['failed', 'error'])}</strong><small>Execution or capture errors</small></div></div>
        <section className="panel"><div className="panel-toolbar"><h2>Recent traces <span>{visible.length}</span></h2><div className="tools"><input aria-label="Search traces" placeholder="Search agent or trace…" value={query} onChange={e => setQuery(e.target.value)}/><select aria-label="Status filter" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All statuses</option>{['success','rejected','failed','error'].map(x => <option key={x}>{x}</option>)}</select></div></div>
          <div className="table-scroll"><table><thead><tr><th>TRACE ID</th><th>AGENT</th><th>DECISION</th><th>STATUS</th><th>CAPTURED</th><th/></tr></thead><tbody>{visible.map(t => <tr key={t.id}><td><button className="trace-link" onClick={() => {setSelected(t.id); setTab('timeline')}}>{short(t.id)}</button></td><td><div className="agent-name">{t.agent}</div><small>v{t.version}</small></td><td><span className="action">{t.action || 'NO PROPOSAL'}</span>{t.amount > 0 && <small>{money(t.amount)} {t.asset}</small>}</td><td><Badge status={t.status}/></td><td><span>{new Date(t.timestamp).toLocaleDateString()}</span><small>{new Date(t.timestamp).toLocaleTimeString()}</small></td><td><button aria-label={'Open trace ' + short(t.id)} className="arrow" onClick={() => {setSelected(t.id); setTab('timeline')}}>↗</button></td></tr>)}</tbody></table></div>
          {!visible.length && <div className="empty">{loading ? 'Loading verified traces…' : traces.length ? 'No traces match these filters.' : 'No decisions recorded yet. Run tracefi demo to begin.'}</div>}
          <div className="panel-bottom"><span className="dot"/> Verified snapshot hashes · captured data, never hidden chain of thought</div>
        </section>
        <div className="footnote">A trace explains the recorded process. A successful execution does not imply a sound financial outcome.</div>
      </> : !trace ? !error && <div className="empty">Verifying trace integrity…</div> : <>
        <div className="decision-card"><div><span className="eyebrow">RECORDED PROPOSAL</span><h2>{trace.proposal?.action || 'No proposal'} <span>{money(trace.proposal?.amount)} {trace.proposal?.asset || ''}</span></h2><p>{trace.proposal?.protocol || '—'} <span className="slash">/</span> {trace.agent.name}@{trace.agent.version}</p></div><div className="decision-status"><Badge status={trace.status}/><small>✓ Snapshot integrity verified</small></div></div>
        <div className="stats provenance-stats"><div><span>MARKET APY</span><strong>{percent(trace.context?.apy)}</strong><small>Recorded yield at decision time</small></div><div><span>PROTOCOL LIQUIDITY</span><strong>{money(trace.context?.liquidity)}</strong><small>Reported snapshot value</small></div><div><span>PORTFOLIO USDC</span><strong>{money(trace.portfolio?.USDC)}</strong><small>Captured asset balance</small></div><div><span>EXPOSURE LIMIT</span><strong>{percent(trace.policy_configuration?.max_exposure)}</strong><small>Recorded risk policy</small></div></div>
        <div className="trace-layout"><section className="panel trace-panel"><div className="tabs">{['timeline','context','evidence','post-mortem','counterfactual'].map(x => <button key={x} className={tab === x ? 'chosen' : ''} onClick={() => setTab(x)}>{x === 'post-mortem' ? 'Failure attribution' : x}</button>)}<a className="download" href={'/api/traces/' + trace.trace_id + '/export'} download={'tracefi-' + short(trace.trace_id) + '.html'}>Export ↗</a></div>
          {tab === 'timeline' && <div className="timeline"><div className="timeline-start"><span className="node"/><code>{new Date(trace.timestamp).toISOString().slice(11,23)}</code><strong>Trace started</strong></div>{trace.spans.map(s => <div key={s.id} className={'timeline-item ' + (s.status === 'error' ? 'span-error' : '')}><span className="node"/><div className="timeline-meta"><code>{new Date(s.start).toISOString().slice(11,23)}</code><small>{(s.duration_ns / 1e6).toFixed(2)} ms</small></div><details><summary><span className="stage">{s.type}</span><strong>{s.name}</strong><Badge status={s.status}/></summary>{s.events.map((e,i) => <Json key={i} value={e.payload}/>)}{s.error && <Json value={s.error}/>}</details></div>)}<div className="timeline-start end"><span className="node"/><code>{new Date(trace.end).toISOString().slice(11,23)}</code><strong>Trace ended</strong></div><p className="timeline-caption">Times shown in UTC. Durations use a monotonic clock.</p></div>}
          {tab === 'context' && <div className="tab-content"><h3>Market, portfolio & risk policy</h3><p>Frozen context, portfolio and configurations used for replay.</p><Json value={{context:trace.context,portfolio:trace.portfolio,agent_configuration:trace.agent_configuration,policy_configuration:trace.policy_configuration}}/></div>}
          {tab === 'evidence' && <div className="tab-content"><h3>Retrieved evidence & decision factors</h3><p>Retrieved records and stated decision factors.</p><Json value={{retrieval:trace.retrieval,rationale:trace.proposal?.rationale,policy:trace.policy,simulation:trace.simulation,execution:trace.execution,outcome:trace.outcome}}/></div>}
          {tab === 'counterfactual' && <Experiment key={trace.trace_id} trace={trace}/>}
          {tab === 'post-mortem' && <div className="tab-content"><div className="eyebrow">LIKELY FAILURE CLASS</div><h3 className="failure-class">{report.likely_failure_class || 'Undetermined'}</h3>{report.findings.map((f,i) => <div className="finding" key={i}><span className="stage">{f.certainty}</span><strong>{f.type}</strong><p>{f.evidence}</p><code>{f.path}</code></div>)}{(report.input_errors || []).map((error,i) => <div className="finding" key={`invalid-${i}`}><strong>Invalid observation</strong><p>{error}</p></div>)}{!report.findings.length && <p>No failure detected by available rules.</p>}<div className="coverage">{Object.entries(report.coverage).map(([key,value]) => <div key={key}><span>{key}</span><span>{value}</span></div>)}</div><p className="footnote">{report.limitations}</p></div>}
        </section><div className="detail-aside"><section className="panel"><h3>Trace identity</h3><label>TRACE ID</label><code className="hash">{trace.trace_id}</code><label>AGENT</label><p>{trace.agent.name}<small>Version {trace.agent.version}</small></p><label>DURATION</label><p>{(trace.duration_ns / 1e6).toFixed(2)} ms</p><label>SPANS</label><p>{trace.spans.length}</p></section><section className="panel"><h3>State fingerprints</h3>{['context_hash','portfolio_hash','policy_hash','agent_config_hash'].map(key => <div key={key}><label>{key.replace('_hash','').replaceAll('_',' ').toUpperCase()}</label><code title={trace[key]} className="hash">{trace[key]}</code></div>)}<div className="hash-note">SHA-256 · {trace.canonical_version}<br/>Hashes detect changes against a trusted reference; they are not signatures.</div></section></div></div>
      </>}
      </div><footer><span>TraceFi</span> Decision provenance, failure attribution and counterfactual debugging for financial agents.</footer>
    </main></div>
}
createRoot(document.getElementById('root')).render(<App/>);
