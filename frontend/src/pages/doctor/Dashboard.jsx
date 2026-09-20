import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { ErrorState, Loading, EmptyState, Pill } from '../../components/States';

const FILTERS = [
  ['all', 'All patients'],
  ['waiting', 'Waiting'],
  ['called', 'Called'],
  ['in_consultation', 'In consultation'],
];

function displayPriority(value) {
  const v = String(value || '').replaceAll('_', ' ').trim();
  return v ? v.charAt(0).toUpperCase() + v.slice(1) : 'Routine';
}

function queueMeta(item) {
  const department = item.department || 'General Medicine';
  const reason = item.reason || 'Reason not recorded';
  return `${department} · ${reason}`;
}

export default function Dashboard() {
  const auth = useAuth(), nav = useNavigate();
  const [queue, setQueue] = useState(null), [error, setError] = useState(null);
  const [busy, setBusy] = useState(null), [filter, setFilter] = useState('all');
  const [lastUpdated, setLastUpdated] = useState(null);

  async function load() {
    setError(null);
    try {
      const r = await api.doctorQueue(auth.token);
      setQueue(r.queue || []);
      setLastUpdated(new Date());
    } catch (e) { setError(e); }
  }

  useEffect(() => { load(); }, [auth.token]);

  async function call(id) {
    setBusy(id);
    try { await api.updateEncounterStatus(auth.token, id, { status: 'called' }); await load(); }
    catch (e) { setError(e); }
    finally { setBusy(null); }
  }

  const metrics = useMemo(() => {
    const items = queue || [];
    return {
      total: items.length,
      waiting: items.filter(x => x.status === 'waiting').length,
      called: items.filter(x => x.status === 'called').length,
      consultation: items.filter(x => x.status === 'in_consultation').length,
      priority: items.filter(x => ['urgent', 'emergency'].includes(String(x.priority || '').toLowerCase())).length,
    };
  }, [queue]);

  const visibleQueue = useMemo(() => {
    const items = queue || [];
    return filter === 'all' ? items : items.filter(item => item.status === filter);
  }, [queue, filter]);

  if (!queue && !error) return <Loading label="Loading your priority queue…" />;

  return <div className="doctor-page doctor-dashboard">
    <div className="doctor-page-head dashboard-head">
      <div>
        <div className="eyebrow">CLINICAL WORKSPACE · TODAY</div>
        <h1>Good day, {auth.user?.name?.split(' ').slice(-1)[0] || 'Doctor'}.</h1>
        <p>Your assigned patients, ordered by operational priority.</p>
      </div>
      <div className="dashboard-head-actions">
        {lastUpdated && <span className="queue-date">Updated {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>}
        <button className="btn btn-outline" onClick={load} disabled={!!busy}>↻ Refresh</button>
      </div>
    </div>

    <ErrorState error={error} onRetry={load} />

    <section className="doctor-metrics" aria-label="Today's queue summary">
      <article className="doctor-metric primary"><span>Total assigned</span><strong>{metrics.total}</strong><small>patients in today's queue</small></article>
      <article className="doctor-metric"><span>Waiting</span><strong>{metrics.waiting}</strong><small>ready to be called</small></article>
      <article className="doctor-metric"><span>In consultation</span><strong>{metrics.consultation}</strong><small>currently being reviewed</small></article>
      <article className={`doctor-metric ${metrics.priority ? 'attention' : ''}`}><span>Priority review</span><strong>{metrics.priority}</strong><small>{metrics.priority ? 'urgent or emergency' : 'no urgent signals in queue'}</small></article>
    </section>

    <section className="queue-card card">
      <div className="section-head queue-section-head">
        <div><div className="eyebrow">ASSIGNED ENCOUNTERS</div><h2>Patient queue</h2><p className="queue-helper">Open an encounter for the full clinical handoff and safety review.</p></div>
        <span className="queue-count">{visibleQueue.length} {visibleQueue.length === 1 ? 'patient' : 'patients'}</span>
      </div>

      <div className="queue-filters" role="tablist" aria-label="Filter patient queue">
        {FILTERS.map(([value, label]) => <button key={value} type="button" role="tab" aria-selected={filter === value} className={filter === value ? 'selected' : ''} onClick={() => setFilter(value)}>{label}<span>{value === 'all' ? metrics.total : metrics[value === 'in_consultation' ? 'consultation' : value]}</span></button>)}
      </div>

      {visibleQueue.length ? <div className="queue-list polished-queue-list">
        {visibleQueue.map((item, index) => <article className={`queue-item polished-queue-item ${String(item.priority || '').toLowerCase()}`} key={item.id}>
          <div className="queue-position" aria-label={`Queue position ${item.queue_position || index + 1}`}>{item.queue_position || index + 1}</div>
          <div className="queue-person">
            <div className="queue-person-name"><strong>{item.patient_name || 'Patient'}</strong><span className="queue-token">Token A-{String(item.token_number).padStart(3, '0')}</span></div>
            <span>{queueMeta(item)}</span>
          </div>
          <div className="queue-meta">
            <Pill value={item.priority || 'routine'} />
            <Pill value={item.status} />
          </div>
          <div className="queue-actions">
            {item.status === 'waiting' && <button className="btn btn-light" onClick={() => call(item.id)} disabled={busy === item.id}>{busy === item.id ? 'Calling…' : 'Call patient'}</button>}
            <button className="btn btn-primary" onClick={() => nav(`/doctor/encounter/${item.id}`)}>Open encounter →</button>
          </div>
        </article>)}
      </div> : <EmptyState title={filter === 'all' ? 'No active encounters' : `No ${FILTERS.find(x => x[0] === filter)?.[1].toLowerCase()} patients`} text={filter === 'all' ? 'Your assigned queue is clear.' : 'Try another queue filter or refresh the workspace.'} />}
    </section>
  </div>;
}
