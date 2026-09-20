import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from './AuthContext';

const Ctx = createContext(null);
const defaults = { language: 'en-IN', input_mode: 'hybrid', font_scale: '1.0', high_contrast: false, reduced_motion: false, captions: true, audio_enabled: true, audio_speed: '1.0', assisted_mode: false };

function apply(prefs) {
  const root = document.documentElement;
  root.style.setProperty('--font-scale', prefs?.font_scale || '1.0');
  document.body.classList.toggle('high-contrast', !!prefs?.high_contrast);
  document.body.classList.toggle('reduced-motion', !!prefs?.reduced_motion);
}

export function PatientPreferencesProvider({ children }) {
  const auth = useAuth();
  const [preferences, setPreferences] = useState(defaults);
  const [capabilities, setCapabilities] = useState(null);
  useEffect(() => {
    let active = true;
    if (auth.user?.role !== 'patient') return undefined;
    Promise.all([api.accessibility(auth.token, auth.user.id), api.accessibilityCapabilities(auth.token)]).then(([p, c]) => {
      if (!active) return;
      const next = { ...defaults, ...(p.preferences || {}) };
      setPreferences(next); setCapabilities(c); apply(next);
    }).catch(() => apply(defaults));
    return () => { active = false; apply(defaults); };
  }, [auth.user?.id, auth.token, auth.user?.role]);
  async function save(next) {
    const result = await api.saveAccessibility(auth.token, auth.user.id, next);
    const saved = { ...defaults, ...result.preferences };
    setPreferences(saved); apply(saved); return saved;
  }
  const value = useMemo(() => ({ preferences, capabilities, save }), [preferences, capabilities]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
export const usePatientPreferences = () => useContext(Ctx);
