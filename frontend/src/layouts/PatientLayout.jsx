import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { usePatientPreferences } from '../context/PatientPreferencesContext';
import { Icon } from '../components/States';
import { loadJourney } from '../utils/storage';
import { patientText } from '../utils/patientText';

const STEP_KEYS = ['language','identity','symptoms','consent','interview','ayush','documents','token'];
function localizedSteps(language){ const t=patientText(language); return STEP_KEYS.map(key=>[key, ({language:t.language,department:t.department,identity:t.identity,symptoms:t.reason,consent:t.consent,interview:t.interview,ayush:t.ayush,documents:t.documents,token:t.token})[key] || key]); }
function journeyStage(j) {
  if (!j.language) return 'language';
  if (!j.identityConfirmed) return 'identity';
  if (!j.reason || !j.encounterId) return 'symptoms';
  if (!j.consent) return 'consent';
  if (!j.interviewComplete) return 'interview';
  if (!j.ayushComplete && !j.ayushSkipped) return 'ayush';
  if (!j.documentsComplete) return 'documents';
  return 'token';
}

export default function PatientLayout() {
  const auth = useAuth(); const nav = useNavigate(); const loc = useLocation(); const { preferences, save } = usePatientPreferences(); const [prefError, setPrefError] = useState(''); const steps = localizedSteps(preferences.language);
  const [stage, setStage] = useState(() => journeyStage(loadJourney(auth.user?.id)));
  useEffect(() => {
    const j = loadJourney(auth.user?.id);
    const routeStage = ({'/patient/interview':'interview','/patient/ayush-transition':'interview','/patient/ayush':'ayush','/patient/documents':'documents','/patient/completion':'token'})[loc.pathname];
    setStage(routeStage || journeyStage(j));
  }, [loc.pathname, auth.user?.id]);
  const currentIndex = Math.max(0, steps.findIndex(([key]) => key === stage));
  const homeView = loc.pathname === '/patient' || (loc.pathname === '/patient/documents' && new URLSearchParams(loc.search).get('library') === '1');
  function guard(path) {
    const j = loadJourney(auth.user.id); const s = journeyStage(j);
    if (path === '/patient' || path === '/patient/visit') return false;
    if (path === '/patient/interview' || path === '/patient/ayush-transition') { if (path === '/patient/interview' && new URLSearchParams(loc.search).get('rewind') === '1' && j.interviewComplete) return false; if (path === '/patient/ayush-transition' && j.interviewComplete) return false; if (s !== 'interview') return true; }
    if (path === '/patient/ayush' && s !== 'ayush') return true;
    if (path === '/patient/documents' && new URLSearchParams(loc.search).get('library') !== '1' && !j.documentsComplete && !(j.interviewComplete && (j.ayushComplete || j.ayushSkipped))) return true;
    if (path === '/patient/completion' && s !== 'token') return true;
    if (path === '/patient/ayush-transition' && !j.interviewComplete) return true;
    return false;
  }
  useEffect(() => { if (loc.pathname !== '/patient' && guard(loc.pathname)) nav('/patient/visit', { replace: true }); }, [loc.pathname, loc.search]);
  async function signOut() { await auth.logout(); nav('/'); }
  async function toggleAudio() { try { setPrefError(''); await save({ ...preferences, audio_enabled: !preferences.audio_enabled }); } catch (e) { setPrefError('Voice setting could not be saved.'); } }
  return <div className="patient-app">
    <header className="patient-topbar"><button className="wordmark" onClick={() => nav('/patient')}><span className="logo-heart">♥</span><span>Aarogya<span>Saar</span></span></button><div className="top-actions"><button type="button" className="round-control" onClick={toggleAudio} aria-label={preferences.audio_enabled ? patientText(preferences.language).mute : patientText(preferences.language).voiceOn}>{preferences.audio_enabled ? '🔊' : '🔇'}</button><button className="btn btn-quiet" onClick={signOut}>{patientText(preferences.language).exit}</button></div></header>
    <div className={`patient-workspace ${homeView ? 'home-workspace' : ''}`}>{!homeView && <aside className="patient-progress-side" aria-label={patientText(preferences.language).visitProgress||'Visit progress'}>{steps.map(([key,label],i)=><div key={key} className={`side-step ${i < currentIndex ? 'done' : i === currentIndex ? 'current' : ''}`}><span>{i < currentIndex ? '✓' : i + 1}</span><b>{label}</b></div>)}</aside>}<main className="patient-main">{prefError && <div className="error-state" role="alert"><div><strong>{patientText(preferences.language).settingsError}</strong><p>{prefError}</p></div><button className="btn btn-light" onClick={() => setPrefError('')}>{patientText(preferences.language).close||'Close'}</button></div>}<Outlet /></main></div>
    <footer className="patient-footer"><span><Icon name="lock" /> {patientText(preferences.language).secure}</span><button onClick={() => nav('/patient')}>{patientText(preferences.language).home}</button></footer>
  </div>;
}
