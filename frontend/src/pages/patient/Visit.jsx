import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { usePatientPreferences } from '../../context/PatientPreferencesContext';
import { ErrorState, Loading } from '../../components/States';
import { LANGUAGES } from '../../utils/constants';
import { loadJourney, saveJourney, clearJourney } from '../../utils/storage';
import { patientValueLabel } from '../../utils/patientText';
import { speakText, stopSpeech } from '../../services/voice/speech';

const COPY = {
  'en-IN': {
    language:'Choose your language', languageHelp:'Choose the language you want to read and hear.',
    identity:'Confirm your identity', identityHelp:'Check the details linked to your patient account before continuing.',
    department:'Choose a department', departmentHelp:'Select the department you want to visit today.',
    reason:'Why are you visiting today?', reasonHelp:'Speak, type, or tap the closest reason.',
    consent:'A simple consent before we begin', consentHelp:'We will record what you tell us so your care team can review it. You can stop before answering the questions.',
    agree:'I understand and agree', continue:'Continue', back:'Back', speak:'Speak your reason', type:'Type your reason',
    name:'Name', age:'Age', gender:'Gender', noProfile:'Patient identity details are not available. Please contact the hospital desk.',
    consentSaved:'Consent is saved for this visit.', hearConsent:'Hear this consent aloud', voiceDone:'Consent explanation finished.', voiceUnavailable:'Voice playback is unavailable. You can read the consent instead.',
    chooseReason:'Or choose', selectDepartment:'Select a department', noDepartments:'No active departments are available right now.', preparing:'Preparing…', saving:'Saving…',
  },
  'hi-IN': {
    language:'अपनी भाषा चुनें', languageHelp:'जिस भाषा में पढ़ना और सुनना आसान लगे, उसे चुनें।',
    identity:'अपनी पहचान की पुष्टि करें', identityHelp:'आगे बढ़ने से पहले अपने मरीज खाते की जानकारी जांच लें।',
    department:'विभाग चुनें', departmentHelp:'आज जिस विभाग में जाना है, उसे चुनें।',
    reason:'आज आप अस्पताल क्यों आए हैं?', reasonHelp:'बोलें, लिखें या सबसे सही कारण चुनें।',
    consent:'शुरू करने से पहले एक छोटी सहमति', consentHelp:'आप जो बताएंगे उसे आपकी देखभाल की टीम देख सकेगी। सवालों से पहले आप रुक सकते हैं।',
    agree:'मैं समझता/समझती हूँ और सहमत हूँ', continue:'आगे बढ़ें', back:'वापस', speak:'कारण बोलें', type:'कारण लिखें',
    name:'नाम', age:'उम्र', gender:'लिंग', noProfile:'मरीज की पहचान की जानकारी उपलब्ध नहीं है। अस्पताल डेस्क से संपर्क करें।',
    consentSaved:'इस विज़िट की सहमति सुरक्षित है।', hearConsent:'सहमति सुनें', voiceDone:'सहमति की जानकारी पूरी हो गई।', voiceUnavailable:'आवाज़ उपलब्ध नहीं है। आप सहमति पढ़ सकते हैं।',
    chooseReason:'या चुनें', selectDepartment:'विभाग चुनें', noDepartments:'अभी कोई सक्रिय विभाग उपलब्ध नहीं है।', preparing:'तैयार हो रहा है…', saving:'सुरक्षित हो रहा है…',
  },
  'bn-IN': {
    language:'আপনার ভাষা বেছে নিন', languageHelp:'যে ভাষায় পড়তে ও শুনতে সহজ, সেটি বেছে নিন।',
    identity:'আপনার পরিচয় নিশ্চিত করুন', identityHelp:'এগিয়ে যাওয়ার আগে আপনার রোগী অ্যাকাউন্টের তথ্য দেখে নিন।',
    department:'বিভাগ বেছে নিন', departmentHelp:'আজ যে বিভাগে যেতে চান সেটি বেছে নিন।',
    reason:'আজ আপনি হাসপাতালে কেন এসেছেন?', reasonHelp:'বলুন, লিখুন অথবা কাছাকাছি কারণটি বেছে নিন।',
    consent:'শুরু করার আগে একটি সহজ সম্মতি', consentHelp:'আপনি যা বলবেন তা আপনার চিকিৎসা দলের সঙ্গে ভাগ করা হবে। প্রশ্ন শুরু করার আগে আপনি থামতে পারেন।',
    agree:'আমি বুঝেছি এবং সম্মত', continue:'এগিয়ে যান', back:'ফিরে যান', speak:'কারণ বলুন', type:'কারণ লিখুন',
    name:'নাম', age:'বয়স', gender:'লিঙ্গ', noProfile:'রোগীর পরিচয়ের তথ্য পাওয়া যায়নি। হাসপাতালের ডেস্কে যোগাযোগ করুন।',
    consentSaved:'এই ভিজিটের সম্মতি সংরক্ষিত হয়েছে।', hearConsent:'সম্মতি শুনুন', voiceDone:'সম্মতির ব্যাখ্যা শেষ হয়েছে।', voiceUnavailable:'ভয়েস পাওয়া যাচ্ছে না। আপনি সম্মতিটি পড়তে পারেন।',
    chooseReason:'অথবা বেছে নিন', selectDepartment:'একটি বিভাগ বেছে নিন', noDepartments:'এই মুহূর্তে কোনো সক্রিয় বিভাগ নেই।', preparing:'প্রস্তুত হচ্ছে…', saving:'সংরক্ষণ হচ্ছে…',
  },
};

const REASONS = [
  ['fever','🌡️',{ 'en-IN':'Fever','hi-IN':'बुखार','bn-IN':'জ্বর' }],
  ['pain','💢',{ 'en-IN':'Pain','hi-IN':'दर्द','bn-IN':'ব্যথা' }],
  ['cough','🫁',{ 'en-IN':'Cough / Cold','hi-IN':'खांसी / जुकाम','bn-IN':'কাশি / সর্দি' }],
  ['weakness','🧍',{ 'en-IN':'Weakness','hi-IN':'कमज़ोरी','bn-IN':'দুর্বলতা' }],
  ['stomach pain','🍽️',{ 'en-IN':'Stomach problem','hi-IN':'पेट की समस्या','bn-IN':'পেটের সমস্যা' }],
  ['headache','🧠',{ 'en-IN':'Headache','hi-IN':'सिरदर्द','bn-IN':'মাথাব্যথা' }],
  ['breathing problem','🌬️',{ 'en-IN':'Breathing problem','hi-IN':'सांस की समस्या','bn-IN':'শ্বাসের সমস্যা' }],
  ['injury','🩹',{ 'en-IN':'Injury','hi-IN':'चोट','bn-IN':'আঘাত' }],
];

function initialStage(journey) {
  if (!journey.language) return 'language';
  if (!journey.identityConfirmed) return 'identity';
  if (!journey.reason) return 'symptoms';
  if (!journey.encounterId) return 'symptoms';
  if (!journey.consent) return 'consent';
  return 'consent';
}

const STAGES = ['language','identity','symptoms','consent'];

export default function Visit() {
  const auth=useAuth(), nav=useNavigate(), {preferences,save}=usePatientPreferences(), id=auth.user.id;
  const [stage,setStage]=useState('language');
  const [patient,setPatient]=useState(null),[department,setDepartment]=useState('General Medicine'),[reason,setReason]=useState('');
  const [checked,setChecked]=useState(false),[consent,setConsent]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(null),[voiceMessage,setVoiceMessage]=useState('');
  const copy=COPY[preferences.language]||COPY['en-IN'];
  const journey=loadJourney(id);

  useEffect(()=>{
    let active=true;
    async function load(){
      setError(null);
      try{
        const [p,c,activeResponse,consultationResponse]=await Promise.all([
          api.patient(auth.token,id),
          api.consent(auth.token,id),
          api.activeEncounter(auth.token,id),
          api.consultations(auth.token,id),
        ]);
        if(!active)return;
        setPatient(p);setConsent(c);
        const storedJourney=loadJourney(id);
        const activeEncounter=activeResponse?.encounter||null;
        // The backend is authoritative for resumability. A client-side journey
        // record without a genuinely active encounter is stale and must never
        // be allowed to push a new visit past language selection.
        const resumable=!!activeEncounter;
        const j=resumable ? storedJourney : {};
        if(!resumable && Object.keys(storedJourney).length){
          clearJourney(id);
          try { sessionStorage.removeItem(`aarogyasaar.ayush.${id}`); } catch {}
        }
        const visitConsultations=(consultationResponse?.consultations||[]).filter(x=>x.encounter_id===activeEncounter?.id);
        const handoff=visitConsultations.find(x=>x.title!=='Clinical consultation'&&x.title!=='AYUSH / Ayurveda intake');
        const ayushHandoff=visitConsultations.find(x=>x.title==='AYUSH / Ayurveda intake');
        const hydrated={
          language:j.language||'',
          identityConfirmed:j.identityConfirmed||false,
          encounterId:activeEncounter?.id||j.encounterId,
          department:activeEncounter?.department||j.department||'General Medicine',
          reason:activeEncounter?.reason||j.reason||'',
          careType:activeEncounter?.care_type||j.careType||'allopathy',
          // Consent is part of the current journey. A previous patient-level
          // consent record must not make a fresh visit skip its consent step.
          // A resumable journey still requires its stored consent plus the
          // backend's active consent record.
          consent:resumable ? !!(j.consent && c?.granted) : false,
          interviewComplete:!!(j.interviewComplete||handoff),
          ayushComplete:!!(j.ayushComplete||ayushHandoff),
          ayushSkipped:!!j.ayushSkipped,
          documentsComplete:!!j.documentsComplete,
        };
        saveJourney(id,hydrated);
        setDepartment(hydrated.department);setReason(hydrated.reason);setChecked(hydrated.consent);
        if(hydrated.documentsComplete){nav('/patient/completion',{replace:true});return;}
        if(hydrated.interviewComplete && !hydrated.ayushComplete && !hydrated.ayushSkipped){nav('/patient/ayush-transition',{replace:true});return;}
        if(hydrated.interviewComplete && (hydrated.ayushComplete || hydrated.ayushSkipped)){nav('/patient/documents',{replace:true});return;}
        setStage(initialStage(hydrated));
      }catch(e){if(active)setError(e)}
    }
    load();
    return()=>{active=false;stopSpeech()};
  },[id,auth.token,nav]);

  const reasonCards=useMemo(()=>REASONS.map(([value,icon,labels])=>[value,icon,labels[preferences.language]||labels['en-IN']]),[preferences.language]);
  const stageNumber=STAGES.indexOf(stage)+1;
  const stageLabel=preferences.language==='hi-IN'?'चरण':preferences.language==='bn-IN'?'ধাপ':'STEP';
  const ofLabel=preferences.language==='hi-IN'?'में से':preferences.language==='bn-IN'?'এর মধ্যে':'OF';

  async function chooseLanguage(language){setBusy(true);setError(null);try{await save({...preferences,language});saveJourney(id,{language});setStage('identity')}catch(e){setError(e)}finally{setBusy(false)}}
  function confirmIdentity(){if(!patient?.name||patient.age==null||!patient.gender){setError(new Error(copy.noProfile));return}saveJourney(id,{identityConfirmed:true});setStage('symptoms')}
  async function continueReason(){
    if(!reason.trim()){setError(new Error(copy.reasonHelp));return}
    setBusy(true);setError(null);
    try{
      const active=await api.activeEncounter(auth.token,id);let e=active.encounter;
      if(e){const r=await api.updateEncounterIntake(auth.token,e.id,{reason:reason.trim(),care_type:'allopathy'});e=r.encounter}
      else{const r=await api.createEncounter(auth.token,{patient_id:id,department,priority:'normal',reason:reason.trim(),care_type:'allopathy'});e=r.encounter;saveJourney(id,{interviewComplete:false,ayushComplete:false,ayushSkipped:false,documentsComplete:false})}
      saveJourney(id,{encounterId:e.id,department:e.department,careType:'allopathy',reason:reason.trim(),symptom:reason.trim()});
      setStage('consent');
    }catch(e){setError(e)}finally{setBusy(false)}
  }
  async function readConsent(){stopSpeech();setVoiceMessage('');try{await speakText(auth.token,consentText(preferences.language),preferences.language,preferences.audio_speed);setVoiceMessage(copy.voiceDone)}catch{setVoiceMessage(copy.voiceUnavailable)}}
  async function grant(){
    if(!checked){setError(new Error(copy.agree));return}
    if(!loadJourney(id).encounterId){setError(new Error(copy.reasonHelp));setStage('symptoms');return}
    setBusy(true);setError(null);
    try{const r=await api.saveConsent(auth.token,id,{patient_id:id,language:preferences.language,audio_explained:true,granted:true});setConsent(r);saveJourney(id,{consent:true});nav('/patient/interview',{replace:true})}catch(e){setError(e)}finally{setBusy(false)}
  }
  function back(){
    if(busy)return;stopSpeech();setError(null);
    const prev={identity:'language',symptoms:'identity',consent:'symptoms'}[stage];
    if(prev){setStage(prev);return}
  }
  if(!patient&&!error)return <Loading label={preferences.language==='hi-IN'?'मरीज की जानकारी लोड हो रही है…':preferences.language==='bn-IN'?'রোগীর তথ্য লোড হচ্ছে…':'Loading your patient identity…'}/>;

  return <div className="patient-page kiosk-flow">
    <div className="kiosk-heading"><div><div className="eyebrow">{stageLabel} {stageNumber} {ofLabel} {STAGES.length}</div><h1>{stage==='language'?copy.language:stage==='identity'?copy.identity:stage==='symptoms'?copy.reason:copy.consent}</h1><p>{stage==='language'?copy.languageHelp:stage==='identity'?copy.identityHelp:stage==='symptoms'?copy.reasonHelp:copy.consentHelp}</p></div><div className="kiosk-task-icon">{stage==='identity'?'👤':stage==='consent'?'🔐':'💬'}</div></div>
    <ErrorState error={error}/>

    {stage==='language'&&<div className="language-cards">{Object.entries(LANGUAGES).map(([k,v])=><button key={k} className="language-card" onClick={()=>chooseLanguage(k)} disabled={busy}><span>{v}</span><b>→</b></button>)}</div>}

    {stage==='identity'&&<section className="card identity-confirm-card"><div className="identity-summary"><div className="identity-avatar">{patient?.name?.slice(0,1)||'P'}</div><div><div className="eyebrow">{copy.patientAccount}</div><h2>{patient?.name}</h2><p>{patient?.email}</p></div></div><div className="answer-evidence-grid"><div><span>{copy.name}</span><strong>{patient?.name||copy.notAvailable}</strong></div><div><span>{copy.age}</span><strong>{patient?.age??copy.notAvailable}</strong></div><div><span>{copy.gender}</span><strong>{patientValueLabel(patient?.gender,preferences.language)||copy.notAvailable}</strong></div><div><span>{copy.language}</span><strong>{LANGUAGES[preferences.language]}</strong></div></div><div className="bottom-action"><button className="btn btn-outline btn-xl" onClick={back}>← {copy.back}</button><button className="btn btn-primary btn-xl" onClick={confirmIdentity}>{copy.continue} →</button></div></section>}


    {stage==='symptoms'&&<section className="reason-card card"><div className="voice-reason"><textarea className="large-input" rows="4" value={reason} onChange={e=>setReason(e.target.value)} placeholder={copy.type}/></div><div className="answer-mode-title"><strong>{copy.chooseReason}</strong><span>{reason||''}</span></div><div className="symptom-card-grid">{reasonCards.map(([v,icon,label])=><button key={v} className={`symptom-card ${reason===v?'selected':''}`} onClick={()=>setReason(v)}><span>{icon}</span><strong>{label}</strong>{reason===v&&<b>✓</b>}</button>)}</div><div className="bottom-action"><button className="btn btn-outline btn-xl" onClick={back}>← {copy.back}</button><button className="btn btn-primary btn-xl" onClick={continueReason} disabled={busy||!reason.trim()}>{busy?copy.preparing:copy.continue} →</button></div></section>}

    {stage==='consent'&&<section className="consent-simple card"><div className="consent-simple-icon">🔐</div><h2>{preferences.language==='bn-IN'?'চিকিৎসা শুরু করার আগে আপনার সম্মতি দরকার।':preferences.language==='hi-IN'?'चिकित्सा शुरू करने से पहले आपकी सहमति ज़रूरी है।':'Your consent is needed before we begin.'}</h2><div className="consent-detail-grid"><div className="consent-detail"><span>🩺</span><div><strong>{preferences.language==='bn-IN'?'কী হবে':preferences.language==='hi-IN'?'क्या होगा':'What happens'}</strong><p> {preferences.language==='hi-IN'?'आरोग्यसार आपके लक्षण और स्वास्थ्य इतिहास के बारे में कुछ सवाल पूछेगा।':preferences.language==='bn-IN'?'আরোগ্যসার আপনার উপসর্গ ও স্বাস্থ্য ইতিহাস সম্পর্কে কিছু প্রশ্ন করবে।':'AarogyaSaar will ask about your symptoms and health history before consultation.'}</p></div></div><div className="consent-detail"><span>👨‍⚕️</span><div><strong>{preferences.language==='bn-IN'?'কেন':preferences.language==='hi-IN'?'क्यों':'Why'}</strong><p> {preferences.language==='hi-IN'?'इससे डॉक्टर आपकी समस्या को जल्दी समझ सकते हैं।':preferences.language==='bn-IN'?'এতে অনুমোদিত ডাক্তার আপনার সমস্যা দ্রুত বুঝতে পারবেন।':'This helps the authorized doctor understand your problem before consultation.'}</p></div></div><div className="consent-detail"><span>🔒</span><div><strong>{preferences.language==='bn-IN'?'তথ্য কোথায় যাবে':preferences.language==='hi-IN'?'आपकी जानकारी':'Your information'}</strong><p> {preferences.language==='hi-IN'?'आपकी जानकारी इस स्वास्थ्य विज़िट के लिए अधिकृत डॉक्टर के साथ साझा की जाएगी।':preferences.language==='bn-IN'?'আপনার তথ্য এই স্বাস্থ্য ভিজিটের জন্য অনুমোদিত ডাক্তারের সঙ্গে শেয়ার করা হবে।':'Your information is shared with the authorized doctor for this healthcare encounter.'}</p></div></div></div><p>{copy.consentHelp}</p><button className="btn btn-outline btn-xl" onClick={readConsent}>🔊 {copy.hearConsent} · {LANGUAGES[preferences.language]}</button>{voiceMessage&&<div className="voice-note">{voiceMessage}</div>}{consent?.granted&&<div className="success-message" role="status">✓ {copy.consentSaved}</div>}<label className="consent-check-large"><input type="checkbox" checked={checked} onChange={e=>setChecked(e.target.checked)}/><span>{copy.agree}</span></label><div className="bottom-action"><button className="btn btn-outline btn-xl" onClick={back}>← {copy.back}</button><button className="btn btn-primary btn-xl" onClick={grant} disabled={busy||!checked}>{busy?copy.saving:copy.continue} →</button></div></section>}
  </div>;
}
function consentText(language){return language==='hi-IN'?'आप जो जानकारी बताएंगे, उसे आपकी देखभाल की टीम आपकी चिकित्सा जांच के लिए देख सकेगी। आगे बढ़ने के लिए सहमति दें।':language==='bn-IN'?'আপনি যে তথ্য দেবেন, তা আপনার চিকিৎসা দল আপনার চিকিৎসার ইতিহাস বোঝার জন্য ব্যবহার করবে। এগিয়ে যেতে সম্মতি দিন।':'The information you share will be reviewed by your care team to understand your medical history. Please agree to continue.';}
