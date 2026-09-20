import { useNavigate } from 'react-router-dom';
import { Icon } from '../components/States';

const roles = [
  {
    key: 'patient',
    title: 'Patient',
    description: 'Start or continue your consultation',
    icon: 'user',
  },
  {
    key: 'doctor',
    title: 'Doctor',
    description: 'Review patient cases and begin consultation',
    icon: 'doctor',
  },
  {
    key: 'admin',
    title: 'Hospital Administrator',
    description: 'Manage hospital operations and access',
    icon: 'home',
  },
];

function RoleCard({ role, onSelect }) {
  return (
    <button
      type="button"
      className={`landing-role-card landing-role-${role.key}`}
      onClick={() => onSelect(role.key)}
      aria-label={`Continue as ${role.title}`}
    >
      <span className="landing-role-icon"><Icon name={role.icon} /></span>
      <span className="landing-role-content">
        <span className="landing-role-title">{role.title}</span>
        <span className="landing-role-description">{role.description}</span>
      </span>
      <span className="landing-role-arrow" aria-hidden="true">→</span>
    </button>
  );
}

export default function Landing() {
  const nav = useNavigate();

  const selectRole = (role) => {
    nav(`/login?role=${role}`);
  };

  return (
    <div className="landing landing-role-selection">
      <div className="landing-pattern" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>

      <header className="landing-nav landing-role-nav">
        <div className="landing-brand-row">
          <button className="wordmark" type="button" onClick={() => nav('/')} aria-label="AarogyaSaar home">
            <span className="logo-heart">♥</span>
            <span>Aarogya<span>Saar</span></span>
          </button>
          <span className="landing-brand-divider" aria-hidden="true" />
          <span className="landing-brand-subtitle">AI-Assisted Patient Case-Taking &amp; Physician Handoff</span>
        </div>
        <div className="landing-role-nav-right">
          <a className="landing-ayush-mark" href="https://ayush.gov.in/" target="_blank" rel="noreferrer" aria-label="Ministry of Ayush, Government of India">
            <img src="https://commons.wikimedia.org/wiki/Special:FilePath/Logo_Ministry_of_AYUSH.png" alt="Ministry of Ayush, Government of India" />
          </a>
          <div className="landing-trust-mark" aria-label="Healthcare platform">
            <span className="landing-trust-icon"><Icon name="shield" /></span>
            <span>Designed for healthcare</span>
          </div>
        </div>
      </header>

      <main className="landing-role-main">
        <section className="landing-role-intro" aria-labelledby="landing-role-heading">
          <div className="eyebrow">AAROGYASAAR HEALTHCARE PLATFORM</div>
          <h1 id="landing-role-heading">How are you using <span>AarogyaSaar?</span></h1>
          <p>Choose your role to continue to the right workspace.</p>
          <div className="landing-role-message">
            <span className="landing-message-mark" aria-hidden="true">✓</span>
            <span>Simple, accessible healthcare technology for every care setting.</span>
          </div>
        </section>

        <section className="landing-role-grid" aria-label="Choose your role">
          {roles.map((role) => (
            <RoleCard key={role.key} role={role} onSelect={selectRole} />
          ))}
        </section>
      </main>

      <footer className="landing-role-footer">
        <span>Patient-led history</span>
        <span aria-hidden="true">•</span>
        <span>Clinician-reviewed information</span>
        <span aria-hidden="true">•</span>
        <span>Built for Indian care settings</span>
      </footer>
    </div>
  );
}
