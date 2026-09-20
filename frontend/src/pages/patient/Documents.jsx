import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { usePatientPreferences } from '../../context/PatientPreferencesContext';
import { ErrorState, Loading, EmptyState, Pill } from '../../components/States';
import { DOCUMENT_TYPES } from '../../utils/constants';
import { loadJourney, saveJourney } from '../../utils/storage';
import { patientText, patientValueLabel } from '../../utils/patientText';

const DOCUMENT_LABELS = {
  'en-IN': { Prescription: 'Prescription', 'Lab Report': 'Lab Report', 'Discharge Summary': 'Discharge Summary', 'Imaging Report': 'Imaging Report', Other: 'Other' },
  'hi-IN': { Prescription: 'दवाइयों की पर्ची', 'Lab Report': 'जाँच रिपोर्ट', 'Discharge Summary': 'डिस्चार्ज सारांश', 'Imaging Report': 'इमेजिंग रिपोर्ट', Other: 'अन्य' },
  'bn-IN': { Prescription: 'ওষুধের প্রেসক্রিপশন', 'Lab Report': 'ল্যাব রিপোর্ট', 'Discharge Summary': 'ডিসচার্জ সারাংশ', 'Imaging Report': 'ইমেজিং রিপোর্ট', Other: 'অন্যান্য' },
};

const SUGGESTION_TEXT = {
  'en-IN': {
    Prescription: 'Any recent prescription or medicine list',
    'Lab Report': 'Recent blood or other test reports',
    'Imaging Report': 'X-ray, MRI or CT report if you have one',
    'Discharge Summary': 'A previous hospital discharge paper, if any',
  },
  'hi-IN': {
    Prescription: 'हाल की पर्ची या दवाओं की सूची',
    'Lab Report': 'हाल की रक्त जांच या अन्य जांच रिपोर्ट',
    'Imaging Report': 'यदि हो तो एक्स-रे, MRI या CT रिपोर्ट',
    'Discharge Summary': 'यदि हो तो पिछली अस्पताल की डिस्चार्ज पर्ची',
  },
  'bn-IN': {
    Prescription: 'সাম্প্রতিক প্রেসক্রিপশন বা ওষুধের তালিকা',
    'Lab Report': 'সাম্প্রতিক রক্ত বা অন্য পরীক্ষার রিপোর্ট',
    'Imaging Report': 'থাকলে X-ray, MRI বা CT রিপোর্ট',
    'Discharge Summary': 'থাকলে আগের হাসপাতালের ডিসচার্জ কাগজ',
  },
};

const ACTION_TEXT = { 'en-IN': { open:'Open', close:'Close' }, 'hi-IN': { open:'खोलें', close:'बंद करें' }, 'bn-IN': { open:'খুলুন', close:'বন্ধ করুন' } };

const ICONS = { Prescription: '💊', 'Lab Report': '🧪', 'Imaging Report': '🩻', 'Discharge Summary': '📄' };

function suggestions(reason = '') {
  const r = String(reason).toLowerCase();
  const base = [];
  if (r.includes('pain') || r.includes('heart') || r.includes('chest')) base.push('Prescription');
  if (r.includes('fever') || r.includes('weakness')) base.push('Lab Report');
  if (r.includes('injury') || r.includes('back') || r.includes('joint')) base.push('Imaging Report');
  if (r.includes('cough') || r.includes('breath')) base.push('Prescription');
  base.push('Discharge Summary');
  return [...new Set(base)].slice(0, 4);
}

export default function Documents() {
  const auth = useAuth();
  const nav = useNavigate();
  const [searchParams] = useSearchParams();
  const libraryView = searchParams.get('library') === '1';
  const { preferences } = usePatientPreferences();
  const id = auth.user.id;
  const text = patientText(preferences.language);
  const labels = DOCUMENT_LABELS[preferences.language] || DOCUMENT_LABELS['en-IN'];
  const descriptions = SUGGESTION_TEXT[preferences.language] || SUGGESTION_TEXT['en-IN'];
  const actions = ACTION_TEXT[preferences.language] || ACTION_TEXT['en-IN'];
  const journey = loadJourney(id);
  const recs = useMemo(() => suggestions(journey.reason || ''), [journey.reason]);
  const [docs, setDocs] = useState([]);
  const [file, setFile] = useState(null);
  const [type, setType] = useState('Other');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [message, setMessage] = useState('');
  const [openDoc, setOpenDoc] = useState(null);
  const [openUrl, setOpenUrl] = useState('');

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const r = await api.documents(auth.token, id);
      setDocs(r.documents || []);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [auth.token, id]);
  useEffect(() => () => { if (openUrl) URL.revokeObjectURL(openUrl); }, [openUrl]);

  async function openDocument(doc) {
    setError(null);
    try {
      const blob = await api.documentContent(auth.token, doc.id);
      const url = URL.createObjectURL(blob);
      if (openUrl) URL.revokeObjectURL(openUrl);
      setOpenUrl(url);
      setOpenDoc(doc);
    } catch (e) { setError(e); }
  }

  async function upload(e) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setMessage('');
    try {
      const fd = new FormData();
      fd.append('patient_id', String(id));
      fd.append('document_type', type);
      if (journey.encounterId) fd.append('encounter_id', String(journey.encounterId));
      fd.append('file', file);
      await api.uploadDocument(auth.token, fd);
      setFile(null);
      setMessage(preferences.language === 'hi-IN' ? 'दस्तावेज़ इस विज़िट में जोड़ दिया गया है।' : preferences.language === 'bn-IN' ? 'নথিটি এই ভিজিটে যোগ করা হয়েছে।' : 'Document added to this visit.');
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  function skip() {
    saveJourney(id, { documentsComplete: true });
    nav('/patient/completion', { replace: true });
  }

  if (loading) return <Loading label={text.loadingDocs} />;

  return (
    <div className="patient-page document-kiosk">
      <div className="kiosk-heading">
        <div>
          <div className="eyebrow">{libraryView ? text.onVisit : `${text.step} 9 / 10`}</div>
          <h1>{text.docsQuestion}</h1>
          <p>{text.docsHelp}</p>
        </div>
        <div className="kiosk-task-icon">📄</div>
      </div>

      <ErrorState error={error} onRetry={load} />
      {message && <div className="success-message" role="status">✓ {message}</div>}

      {!libraryView && <>      <section className="card">
        <div className="section-head"><div><div className="eyebrow">{text.helpful}</div><h2>{text.helpful}</h2></div></div>
        <div className="document-suggestions">
          {recs.map((kind) => (
            <div className="document-suggestion" key={kind}>
              <span>{ICONS[kind] || '📄'}</span>
              <div><strong>{labels[kind] || kind}</strong><small>{descriptions[kind] || ''}</small></div>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="section-head"><div><div className="eyebrow">{text.optional}</div><h2>{text.addPaper}</h2></div></div>
        <form className="kiosk-upload" onSubmit={upload}>
          <label className="field">
            <span>{text.paperType}</span>
            <select value={type} onChange={(e) => setType(e.target.value)}>
              {DOCUMENT_TYPES.map((kind) => <option key={kind} value={kind}>{labels[kind] || kind}</option>)}
            </select>
          </label>
          <label className="file-picker large-file-picker">
            <input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt" capture="environment" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            <span>{file ? file.name : text.takeFile}</span>
            <small>{text.paperOptional}</small>
          </label>
          <button className="btn btn-primary btn-xl" disabled={!file || busy}>{busy ? text.uploading : text.upload} ↑</button>
        </form>
      </section>

      </>}

      <section className="card">
        <div className="section-head"><div><div className="eyebrow">{text.onVisit}</div><h2>{docs.length ? `${docs.length} ${text.papersAdded}` : text.noPapers}</h2></div></div>
        {docs.length ? (
          <div className="doc-list">
            {docs.map((d) => (
              <article className="doc-row" key={d.id}>
                <span className="doc-icon">📄</span>
                <div><strong>{d.filename}</strong><small>{labels[d.document_type] || d.document_type}</small></div>
                <div className="doc-row-actions"><Pill value={patientValueLabel(d.status,preferences.language)} /><button className="btn btn-light" type="button" onClick={() => openDocument(d)}>{actions.open}</button></div>
              </article>
            ))}
          </div>
        ) : <EmptyState title={text.noDocs} text={text.docsOkay} />}
      </section>

      {!libraryView ? <div className="document-skip">
        <button className="btn btn-primary btn-xl" onClick={skip}>{text.continueToken} →</button>
        <p>{text.medicalOptional}</p>
      </div> : <div className="bottom-action"><button className="btn btn-primary btn-xl" onClick={() => nav('/patient')}>← {text.home}</button></div>}
      {!libraryView && <div className="bottom-action">
        <button className="btn btn-outline btn-xl" onClick={() => { const j=loadJourney(id); if(j.ayushComplete){nav('/patient/ayush');return;} if(j.ayushSkipped){nav('/patient/ayush-transition');return;} nav('/patient/interview?rewind=1'); }}>← {text.back}</button>
      </div>}

      {openDoc && <div className="patient-modal-backdrop" role="presentation" onClick={() => {setOpenDoc(null);if(openUrl)URL.revokeObjectURL(openUrl);setOpenUrl('')}}>
        <div className="patient-modal card document-viewer-modal" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
          <div className="section-head"><div><div className="eyebrow">{labels[openDoc.document_type] || openDoc.document_type}</div><h2>{openDoc.filename}</h2></div><button type="button" className="btn btn-quiet modal-close" aria-label={actions.close} onClick={() => {setOpenDoc(null);if(openUrl)URL.revokeObjectURL(openUrl);setOpenUrl('')}}>×</button></div>
          {openUrl && (openDoc.mime_type?.startsWith('image/') ? <img className="document-preview-image" src={openUrl} alt={openDoc.filename}/> : <iframe className="document-preview-frame" src={openUrl} title={openDoc.filename}/>)}
          {!openUrl && <p className="muted">{text.noDocs}</p>}
        </div>
      </div>}
    </div>
  );
}
