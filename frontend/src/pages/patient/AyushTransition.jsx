import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { usePatientPreferences } from '../../context/PatientPreferencesContext';
import { ErrorState, Loading } from '../../components/States';
import { loadJourney, saveJourney } from '../../utils/storage';

const COPY={
 'en-IN':{eyebrow:'GENERAL DOCTOR ASSESSMENT COMPLETE',title:'Would you also like an AYUSH assessment?',help:'Your General Doctor interview is complete. You can now add an optional AYUSH assessment before your token is prepared.',yes:'Continue with AYUSH',no:'Skip AYUSH',back:'Back to interview',summary:'What we captured',reason:'Reason for visit',fallback:'General Doctor interview',details:'Your answers are securely linked to this hospital encounter.'},
 'hi-IN':{eyebrow:'सामान्य डॉक्टर का आकलन पूरा',title:'क्या आप आयुष आकलन भी करना चाहेंगे?',help:'सामान्य डॉक्टर का साक्षात्कार पूरा हो गया है। टोकन तैयार होने से पहले आप वैकल्पिक आयुष आकलन जोड़ सकते हैं।',yes:'आयुष जारी रखें',no:'आयुष छोड़ें',back:'साक्षात्कार पर वापस जाएँ',summary:'क्या दर्ज किया गया',reason:'आने का कारण',fallback:'सामान्य डॉक्टर का साक्षात्कार',details:'आपके जवाब इसी अस्पताल विज़िट से सुरक्षित रूप से जुड़े हैं।'},
 'bn-IN':{eyebrow:'সাধারণ ডাক্তারের মূল্যায়ন সম্পূর্ণ',title:'আপনি কি একটি আয়ুষ মূল্যায়নও করতে চান?',help:'সাধারণ ডাক্তারের সাক্ষাৎকার সম্পূর্ণ হয়েছে। টোকেন প্রস্তুত হওয়ার আগে আপনি একটি ঐচ্ছিক আয়ুষ মূল্যায়ন যোগ করতে পারেন।',yes:'আয়ুষ চালিয়ে যান',no:'আয়ুষ এড়িয়ে যান',back:'সাক্ষাৎকারে ফিরে যান',summary:'যা নথিভুক্ত হয়েছে',reason:'আসার কারণ',fallback:'সাধারণ ডাক্তারের সাক্ষাৎকার',details:'আপনার উত্তর একই হাসপাতাল ভিজিটের সঙ্গে নিরাপদে যুক্ত আছে।'}
};
export default function AyushTransition(){
 const auth=useAuth(),nav=useNavigate(),{preferences}=usePatientPreferences(),id=auth.user.id,copy=COPY[preferences.language]||COPY['en-IN'];
 const [summary,setSummary]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(null);
 useEffect(()=>{const j=loadJourney(id);if(!j.interviewComplete){nav('/patient/interview',{replace:true});return;} api.clinicalSummary(auth.token,id).then(r=>setSummary(r.clinical_summary)).catch(e=>setError(e));},[id,auth.token,nav]);
 function skip(){saveJourney(id,{ayushComplete:false,ayushSkipped:true,documentsComplete:false});nav('/patient/documents',{replace:true});}
 function continueAyush(){saveJourney(id,{ayushSkipped:false});nav('/patient/ayush',{replace:true});}
 if(!loadJourney(id).interviewComplete)return <Loading label={preferences.language==='hi-IN'?'लोड हो रहा है…':preferences.language==='bn-IN'?'লোড হচ্ছে…':'Loading…'}/>;
 return <div className="patient-page ayush-transition"><div className="kiosk-heading"><div><div className="eyebrow">{copy.eyebrow}</div><h1>{copy.title}</h1><p>{copy.help}</p></div><div className="kiosk-task-icon">🌿</div></div><ErrorState error={error}/><section className="card transition-summary"><div className="eyebrow">{copy.summary}</div><h2>{summary?.headline||summary?.current_visit?.chief_complaint||loadJourney(id).reason||copy.fallback}</h2><p>{copy.reason}: {loadJourney(id).reason||'—'}</p><p className="muted">{copy.details}</p></section><div className="transition-actions"><button className="btn btn-primary btn-xl" onClick={continueAyush} disabled={busy}>🌿 {copy.yes}</button><button className="btn btn-outline btn-xl" onClick={skip} disabled={busy}>{copy.no}</button></div><div className="bottom-action"><button className="btn btn-light btn-xl" onClick={()=>nav('/patient/interview?rewind=1')}>← {copy.back}</button></div></div>;
}
