export function Loading({ label = 'Loading…' }) { return <div className="state-card" role="status"><span className="spinner" aria-hidden="true" />{label}</div>; }
export function ErrorState({ error, onRetry, title = 'We could not complete this step.' }) {
  if (!error) return null;
  const status = Number(error?.status);
  const message = String(error?.message || '').trim();
  const technical = /axios|fetch|request failed|status code|internal server|traceback|exception|undefined|null|networkerror/i.test(message);
  const safeMessage = technical || status >= 500 ? 'Something went wrong while loading your information. Please try again.' : message || 'Please try again.';
  return <div className="error-state" role="alert"><div><strong>{title}</strong><p>{safeMessage}</p></div>{onRetry && <button className="btn btn-light" onClick={onRetry}>Try again</button>}</div>;
}
export function EmptyState({ title, text }) { return <div className="empty-state"><div className="empty-icon">♡</div><strong>{title}</strong><p>{text}</p></div>; }
export function Pill({ value }) { const v = String(value || 'unknown').replaceAll('_', '-'); return <span className={`pill ${v}`}>{String(value || 'Unknown').replaceAll('_', ' ')}</span>; }
export function Section({ title, eyebrow, children, action, className = '' }) { return <section className={`card ${className}`}><div className="section-head"> <div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h2>{title}</h2></div>{action}</div>{children}</section>; }
export function Field({ label, error, hint, children }) { return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}{error && <em>{error}</em>}</label>; }
export function Icon({ name }) { const icons = { heart:'♥', user:'●', doctor:'✚', voice:'◉', check:'✓', arrow:'→', lock:'⌁', language:'文', settings:'⚙', document:'▤', shield:'◇', queue:'☷', home:'⌂', ayush:'✿', history:'◴' }; return <span aria-hidden="true" className="icon">{icons[name] || '•'}</span>; }
