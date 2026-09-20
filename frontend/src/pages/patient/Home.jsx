import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { usePatientPreferences } from '../../context/PatientPreferencesContext';
import { ErrorState, Loading, EmptyState, Pill } from '../../components/States';
import { LANGUAGES } from '../../utils/constants';
import { loadJourney } from '../../utils/storage';
import { patientDepartmentLabel, patientValueLabel } from '../../utils/patientText';

const COPY = {
  'en-IN': {
    eyebrow:'MY HEALTH', title:'Your care, in one simple place.', help:'Your visits, documents and care information are connected to your hospital account.',
    active:'Active Encounter', noActive:'No active encounter', token:'Token', doctor:'Doctor', department:'Department', room:'Room', status:'Status',
    visitToken:'Visit My Token', start:'Start My Visit', pending:'Your consultation is still in progress.',
    profile:'Profile & Identity', edit:'Edit Profile', name:'Name', age:'Age', gender:'Gender', phone:'Contact',
    documents:'Medical Documents', viewDocs:'View Documents', documentsCount:'documents',
    prescription:'Prescription', viewPrescription:'View Prescription', noPrescription:'No prescription yet.',
    reports:'Reports', viewReports:'View Reports', noReports:'No completed consultation reports yet.',
    history:'Medical History', viewHistory:'View History', noHistory:'No completed consultation history yet.',
    latest:'Latest', save:'Save changes', assessment:'Assessment', findings:'Findings', plan:'Plan', diagnosis:'Diagnosis', followUp:'Follow-up', cancel:'Cancel', saved:'Profile updated successfully.', close:'Close',
    noDocs:'No medical documents yet.', noProfile:'Profile information is not available.',
    language:'Language', textSize:'Text size', voice:'Voice', contrast:'High contrast', accessibility:'Accessibility', accessibilityEyebrow:'MAKE IT COMFORTABLE', bloodGroup:'Blood group', allergies:'Allergies', conditions:'Conditions', medicines:'Medicines', address:'Address',
    emptyActive:'Start a new visit when you are ready.', completed:'Completed', consultation:'Consultation',
  },
  'hi-IN': {
    eyebrow:'मेरी स्वास्थ्य जानकारी', title:'आपकी देखभाल, एक आसान जगह पर।', help:'आपकी विज़िट, दस्तावेज़ और देखभाल की जानकारी आपके अस्पताल खाते से जुड़ी है।',
    active:'सक्रिय विज़िट', noActive:'कोई सक्रिय विज़िट नहीं', token:'टोकन', doctor:'डॉक्टर', department:'विभाग', room:'कमरा', status:'स्थिति',
    visitToken:'मेरा टोकन देखें', start:'मेरी विज़िट शुरू करें', pending:'आपका परामर्श अभी जारी है।',
    profile:'प्रोफ़ाइल और पहचान', edit:'प्रोफ़ाइल बदलें', name:'नाम', age:'उम्र', gender:'लिंग', phone:'संपर्क',
    documents:'मेरे दस्तावेज़', viewDocs:'दस्तावेज़ देखें', documentsCount:'दस्तावेज़',
    prescription:'दवाइयों की पर्ची', viewPrescription:'पर्ची देखें', noPrescription:'अभी कोई पर्ची नहीं है।',
    reports:'जाँच रिपोर्ट', viewReports:'रिपोर्ट देखें', noReports:'अभी कोई पूरी हुई विज़िट रिपोर्ट नहीं है।',
    history:'मेडिकल इतिहास', viewHistory:'इतिहास देखें', noHistory:'अभी कोई पूरा मेडिकल इतिहास नहीं है।',
    latest:'नवीनतम', save:'बदलाव सुरक्षित करें', assessment:'आकलन', findings:'जाँच में मिले तथ्य', plan:'आगे की योजना', diagnosis:'निदान', followUp:'आगे की मुलाकात', cancel:'रद्द करें', saved:'प्रोफ़ाइल सफलतापूर्वक बदली गई।', close:'बंद करें',
    noDocs:'अभी कोई मेडिकल दस्तावेज़ नहीं है।', noProfile:'प्रोफ़ाइल जानकारी उपलब्ध नहीं है।',
    language:'भाषा', textSize:'टेक्स्ट आकार', voice:'आवाज़', contrast:'हाई कॉन्ट्रास्ट', accessibility:'सुगमता', accessibilityEyebrow:'आसान इस्तेमाल के लिए', close:'बंद करें', bloodGroup:'ब्लड ग्रुप', allergies:'एलर्जी', conditions:'बीमारियाँ', medicines:'दवाएँ', address:'पता',
    emptyActive:'तैयार होने पर नई विज़िट शुरू करें।', completed:'पूरी', consultation:'परामर्श',
  },
  'bn-IN': {
    eyebrow:'আমার স্বাস্থ্য তথ্য', title:'আপনার চিকিৎসা, এক সহজ জায়গায়।', help:'আপনার ভিজিট, নথি এবং চিকিৎসার তথ্য হাসপাতাল অ্যাকাউন্টের সঙ্গে যুক্ত।',
    active:'চলমান ভিজিট', noActive:'কোনো চলমান ভিজিট নেই', token:'টোকেন', doctor:'ডাক্তার', department:'বিভাগ', room:'কক্ষ', status:'অবস্থা',
    visitToken:'আমার টোকেন দেখুন', start:'আমার ভিজিট শুরু করুন', pending:'আপনার পরামর্শ এখনও চলছে।',
    profile:'প্রোফাইল ও পরিচয়', edit:'প্রোফাইল বদলান', name:'নাম', age:'বয়স', gender:'লিঙ্গ', phone:'যোগাযোগ',
    documents:'আমার নথি', viewDocs:'নথি দেখুন', documentsCount:'নথি',
    prescription:'ওষুধের প্রেসক্রিপশন', viewPrescription:'প্রেসক্রিপশন দেখুন', noPrescription:'এখনও কোনো প্রেসক্রিপশন নেই।',
    reports:'পরীক্ষার রিপোর্ট', viewReports:'রিপোর্ট দেখুন', noReports:'এখনও কোনো সম্পূর্ণ ভিজিট রিপোর্ট নেই।',
    history:'চিকিৎসার ইতিহাস', viewHistory:'ইতিহাস দেখুন', noHistory:'এখনও কোনো সম্পূর্ণ চিকিৎসার ইতিহাস নেই।',
    latest:'সাম্প্রতিক', save:'পরিবর্তন সংরক্ষণ করুন', assessment:'মূল্যায়ন', findings:'পরীক্ষায় পাওয়া তথ্য', plan:'পরবর্তী পরিকল্পনা', diagnosis:'রোগ নির্ণয়', followUp:'পরবর্তী দেখা', cancel:'বাতিল', saved:'প্রোফাইল সফলভাবে আপডেট হয়েছে।', close:'বন্ধ করুন',
    noDocs:'এখনও কোনো চিকিৎসার নথি নেই।', noProfile:'প্রোফাইল তথ্য পাওয়া যায়নি।',
    language:'ভাষা', textSize:'টেক্সটের আকার', voice:'ভয়েস', contrast:'হাই কনট্রাস্ট', accessibility:'সহজ ব্যবহার', accessibilityEyebrow:'সহজে ব্যবহার করুন', close:'বন্ধ করুন', bloodGroup:'রক্তের গ্রুপ', allergies:'অ্যালার্জি', conditions:'রোগ', medicines:'ওষুধ', address:'ঠিকানা',
    emptyActive:'প্রস্তুত হলে নতুন ভিজিট শুরু করুন।', completed:'সম্পূর্ণ', consultation:'পরামর্শ',
  },
};

function formatDate(value){if(!value)return '—';try{return new Date(value).toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'})}catch{return value}}

function firstCompleted(consultations){return consultations.find(c=>c.consultation_status==='completed'||String(c.status).toLowerCase()==='completed')||null}

export default function Home(){
  const auth=useAuth(),nav=useNavigate(),{preferences,save}=usePatientPreferences();
  const id=auth.user.id,copy=COPY[preferences.language]||COPY['en-IN'];
  const [profile,setProfile]=useState(null),[consultations,setConsultations]=useState([]),[docs,setDocs]=useState([]),[active,setActive]=useState(null),[error,setError]=useState(null),[loading,setLoading]=useState(true),[modal,setModal]=useState(null),[form,setForm]=useState(null),[busy,setBusy]=useState(false);

  async function load(){
    setLoading(true);setError(null);
    try{
      const [p,c,d,a]=await Promise.all([api.patient(auth.token,id),api.consultations(auth.token,id),api.documents(auth.token,id),api.activeEncounter(auth.token,id)]);
      setProfile(p);setConsultations(c.consultations||[]);setDocs(d.documents||[]);setActive(a.encounter||null);
    }catch(e){setError(e)}finally{setLoading(false)}
  }
  useEffect(()=>{load()},[id,auth.token]);

  const completed=useMemo(()=>firstCompleted(consultations),[consultations]);
  const prescription=useMemo(()=>consultations.find(c=>c.consultation_status==='completed' && String(c.sections?.prescription||'').trim())||null,[consultations]);
  const reportDocs=useMemo(()=>docs.filter(d=>['Lab Report','Imaging Report','Discharge Summary'].includes(d.document_type)),[docs]);
  const reportCount=reportDocs.length+(completed?1:0);

  function editProfile(){setForm({name:profile?.name||'',age:profile?.age??'',gender:profile?.gender||'',phone:profile?.phone||'',blood_group:profile?.blood_group||'',allergies:profile?.allergies||'',conditions:profile?.conditions||'',medications:profile?.medications||'',address:profile?.address||''});setModal('profile')}
  async function saveProfile(){
    setBusy(true);setError(null);
    try{const r=await api.updatePatient(auth.token,id,{...form,age:form.age===''?null:Number(form.age)});setProfile(r.patient);setModal(null);await load()}
    catch(e){setError(e)}finally{setBusy(false)}
  }

  if(loading)return <Loading label={preferences.language==='hi-IN'?'आपका स्वास्थ्य रिकॉर्ड लोड हो रहा है…':preferences.language==='bn-IN'?'আপনার স্বাস্থ্য রেকর্ড লোড হচ্ছে…':'Loading your health record…'}/>;

  const activePending=Boolean(active);
  const journey=loadJourney(id);
  const activeCtaPath=journey.documentsComplete ? '/patient/completion' : '/patient/visit';
  return <div className="patient-page health-dashboard final-patient-home">
    <div className="home-hero">
      <div><div className="eyebrow">{copy.eyebrow}</div><h1>{copy.title}</h1><p>{copy.help}</p></div>
    </div>
    <ErrorState error={error} onRetry={load}/>

    <div className="patient-home-cards">
      <section className="home-function-card active-encounter-card">
        <div className="home-card-icon">🎫</div>
        <div className="home-card-content"><div className="eyebrow">{copy.active}</div><h2>{activePending?copy.pending:copy.noActive}</h2>
          {activePending?<div className="home-fact-row"><span>{copy.token} <strong>A-{String(active.token_number).padStart(3,'0')}</strong></span><span>{copy.doctor} <strong>{active.doctor_name||'—'}</strong></span><span>{copy.department} <strong>{patientDepartmentLabel(active.department||'—',preferences.language)}</strong></span><span>{copy.room} <strong>{active.doctor_room_number||'—'}</strong></span><span>{copy.status} <strong>{patientValueLabel(active.status,preferences.language)||'—'}</strong></span></div>:<p>{copy.emptyActive}</p>}
          <button className="btn btn-primary btn-xl" onClick={()=>nav(activeCtaPath)}>{activePending?(journey.documentsComplete?copy.visitToken:copy.start):copy.start} →</button>
        </div>
      </section>

      <section className="home-function-card">
        <div className="home-card-icon">👤</div>
        <div className="home-card-content"><div className="eyebrow">{copy.profile}</div><h2>{profile?.name||copy.noProfile}</h2>
          <div className="home-fact-row"><span>{copy.age} <strong>{profile?.age??'—'}</strong></span><span>{copy.gender} <strong>{patientValueLabel(profile?.gender,preferences.language)||'—'}</strong></span><span>{copy.phone} <strong>{profile?.phone||'—'}</strong></span></div>
          <button className="btn btn-outline btn-xl" onClick={editProfile}>{copy.edit}</button>
        </div>
      </section>

      <section className="home-function-card">
        <div className="home-card-icon">📄</div>
        <div className="home-card-content"><div className="eyebrow">{copy.documents}</div><h2>{docs.length} {copy.documentsCount}</h2><p>{docs.length?docs.slice(0,2).map(d=>d.filename).join(' · '):copy.noDocs}</p>
          <button className="btn btn-outline btn-xl" onClick={()=>nav('/patient/documents?library=1')}>{copy.viewDocs} →</button>
        </div>
      </section>

      <section className="home-function-card">
        <div className="home-card-icon">💊</div>
        <div className="home-card-content"><div className="eyebrow">{copy.prescription}</div><h2>{prescription?copy.latest:copy.noPrescription}</h2>{prescription&&<p>{prescription.doctor_name||copy.doctor} · {formatDate(prescription.visit_date||prescription.created_at)}</p>}
          <button className="btn btn-outline btn-xl" disabled={!prescription} onClick={()=>prescription&&setModal('prescription')}>{copy.viewPrescription} →</button>
        </div>
      </section>

      <section className="home-function-card">
        <div className="home-card-icon">🧪</div>
        <div className="home-card-content"><div className="eyebrow">{copy.reports}</div><h2>{reportCount?`${reportCount} ${copy.reports}`:copy.noReports}</h2><p>{reportDocs.length?reportDocs.slice(0,2).map(d=>d.filename).join(' · '):completed?(preferences.language==='hi-IN'?'परामर्श रिपोर्ट':preferences.language==='bn-IN'?'পরামর্শের রিপোর্ট':'Consultation report'):'—'}</p>
          <button className="btn btn-outline btn-xl" disabled={!reportCount} onClick={()=>reportDocs.length?nav('/patient/documents?library=1'):setModal('report')}>{copy.viewReports} →</button>
        </div>
      </section>

      <section className="home-function-card">
        <div className="home-card-icon">🩺</div>
        <div className="home-card-content"><div className="eyebrow">{copy.history}</div><h2>{completed?copy.latest:copy.noHistory}</h2>
          {completed&&<div className="home-history-preview"><strong>{completed.doctor_name||copy.doctor}</strong><span>{patientDepartmentLabel(completed.department||'—',preferences.language)} · {formatDate(completed.visit_date||completed.created_at)}</span><span>{completed.sections?.assessment||completed.summary||(preferences.language==='hi-IN'?'परामर्श पूरा हुआ':preferences.language==='bn-IN'?'পরামর্শ সম্পূর্ণ হয়েছে':'Consultation completed')}</span></div>}
          <button className="btn btn-outline btn-xl" disabled={!completed} onClick={()=>completed&&setModal('history')}>{copy.viewHistory} →</button>
        </div>
      </section>
    </div>

    <section className="card patient-preferences-card">
      <div className="section-head"><div><div className="eyebrow">{copy.accessibilityEyebrow}</div><h2>{copy.accessibility}</h2></div></div>
      <div className="preference-grid">
        <div className="pref-card"><span className="pref-icon">文</span><div><strong>{copy.language}</strong><small>{LANGUAGES[preferences.language]}</small></div><select value={preferences.language} onChange={e=>save({...preferences,language:e.target.value})}>{Object.entries(LANGUAGES).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></div>
        <div className="pref-card"><span className="pref-icon">Aa</span><div><strong>{copy.textSize}</strong></div><select value={preferences.font_scale} onChange={e=>save({...preferences,font_scale:e.target.value})}><option value="1.0">100%</option><option value="1.15">115%</option><option value="1.3">130%</option><option value="1.5">150%</option><option value="1.75">175%</option><option value="2.0">200%</option></select></div>
        <div className="pref-card toggle-card"><span className="pref-icon">🎤</span><div><strong>{copy.voice}</strong><small>{patientValueLabel(preferences.audio_enabled?'On':'Off',preferences.language)}</small></div><button type="button" className={`switch ${preferences.audio_enabled?'on':''}`} aria-pressed={preferences.audio_enabled} onClick={()=>save({...preferences,audio_enabled:!preferences.audio_enabled})}><span/></button></div>
        <div className="pref-card toggle-card"><span className="pref-icon">◐</span><div><strong>{copy.contrast}</strong><small>{patientValueLabel(preferences.high_contrast?'On':'Off',preferences.language)}</small></div><button type="button" className={`switch ${preferences.high_contrast?'on':''}`} aria-pressed={preferences.high_contrast} onClick={()=>save({...preferences,high_contrast:!preferences.high_contrast})}><span/></button></div>
      </div>
    </section>

    {modal==='profile'&&<div className="patient-modal-backdrop" role="presentation"><div className="patient-modal card" role="dialog" aria-modal="true"><div className="section-head"><div><div className="eyebrow">{copy.profile}</div><h2>{copy.edit}</h2></div><button type="button" className="btn btn-quiet modal-close" aria-label={copy.close} onClick={()=>setModal(null)}>×</button></div><div className="profile-edit-grid">
      {[['name',copy.name],['age',copy.age],['gender',copy.gender],['phone',copy.phone],['blood_group',copy.bloodGroup],['allergies',copy.allergies],['conditions',copy.conditions],['medications',copy.medicines],['address',copy.address]].map(([k,label])=><label className="field" key={k}><span>{label}</span><input value={form?.[k]??''} onChange={e=>setForm({...form,[k]:e.target.value})}/></label>)}
    </div><div className="bottom-action"><button className="btn btn-outline btn-xl" onClick={()=>setModal(null)}>{copy.cancel}</button><button className="btn btn-primary btn-xl" disabled={busy} onClick={saveProfile}>{busy?(preferences.language==='hi-IN'?'सुरक्षित हो रहा है…':preferences.language==='bn-IN'?'সংরক্ষণ হচ্ছে…':'Saving…'):copy.save}</button></div></div></div>}

    {modal==='prescription'&&prescription&&<RecordModal title={copy.prescription} close={()=>setModal(null)} closeLabel={copy.close}><h3>{prescription.doctor_name||copy.doctor}</h3><p>{prescription.sections?.prescription||prescription.summary}</p><small>{formatDate(prescription.visit_date||prescription.created_at)}</small></RecordModal>}
    {modal==='report'&&completed&&<RecordModal title={copy.reports} close={()=>setModal(null)} closeLabel={copy.close}><p><strong>{completed.doctor_name||copy.doctor}</strong> · {patientDepartmentLabel(completed.department||'—',preferences.language)} · {formatDate(completed.visit_date||completed.created_at)}</p><p><strong>{copy.assessment}:</strong> {completed.sections?.assessment||'—'}</p><p><strong>{copy.findings}:</strong> {completed.sections?.examination||'—'}</p><p><strong>{copy.plan}:</strong> {completed.sections?.plan||'—'}</p></RecordModal>}
    {modal==='history'&&completed&&<RecordModal title={copy.history} close={()=>setModal(null)} closeLabel={copy.close}><p><strong>{completed.doctor_name||copy.doctor}</strong> · {patientDepartmentLabel(completed.department||'—',preferences.language)} · {formatDate(completed.visit_date||completed.created_at)}</p><p><strong>{copy.assessment}:</strong> {completed.sections?.assessment||'—'}</p><p><strong>{copy.diagnosis}:</strong> {completed.sections?.diagnosis||'—'}</p><p><strong>{copy.plan}:</strong> {completed.sections?.plan||'—'}</p><p><strong>{copy.followUp}:</strong> {completed.sections?.follow_up||'—'}</p></RecordModal>}
  </div>
}
function RecordModal({title,close,closeLabel,children}){return <div className="patient-modal-backdrop"><div className="patient-modal card" role="dialog" aria-modal="true"><div className="section-head"><h2>{title}</h2><button type="button" className="btn btn-quiet modal-close" aria-label={closeLabel} onClick={close}>×</button></div><div className="record-modal-content">{children}</div><button className="btn btn-primary btn-xl" onClick={close}>{closeLabel}</button></div></div>}
