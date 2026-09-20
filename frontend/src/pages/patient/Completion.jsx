import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { usePatientPreferences } from '../../context/PatientPreferencesContext';
import { ErrorState, Loading } from '../../components/States';
import { loadJourney, saveJourney } from '../../utils/storage';
import { patientDepartmentLabel } from '../../utils/patientText';

const COPY={
 'en-IN':{ready:'YOU ARE READY',title:'Your token is ready.',help:'Keep this screen with you while you wait for your consultation.',token:'YOUR TOKEN',doctor:'Doctor',room:'Room',care:'Care',department:'Department',choose:'Choose another doctor',close:'Close doctor list',available:'AVAILABLE DOCTORS',noOther:'No other eligible doctor is available.',unchanged:'Your current assignment remains unchanged.',home:'Back to home',connected:'Your encounter stays connected.',connectedHelp:'The token, doctor assignment, history and uploaded papers belong to the same hospital encounter.',assigned:'Your doctor is now',roomNA:'Room not assigned',doctorAssigned:'Assigned doctor',call:'Calling…',select:'Only active doctors eligible for this department are shown.'},
 'hi-IN':{ready:'आप तैयार हैं',title:'आपका टोकन तैयार है।',help:'परामर्श की प्रतीक्षा करते समय इस स्क्रीन को अपने पास रखें।',token:'आपका टोकन',doctor:'डॉक्टर',room:'कमरा',care:'देखभाल',department:'विभाग',choose:'दूसरा डॉक्टर चुनें',close:'डॉक्टर सूची बंद करें',available:'उपलब्ध डॉक्टर',noOther:'कोई दूसरा उपयुक्त डॉक्टर उपलब्ध नहीं है।',unchanged:'आपका वर्तमान डॉक्टर वही रहेगा।',home:'होम पर जाएँ',connected:'आपकी विज़िट जुड़ी हुई है।',connectedHelp:'टोकन, डॉक्टर, इतिहास और अपलोड किए गए कागज़ इसी एनकाउंटर से जुड़े हैं।',assigned:'आपके डॉक्टर अब हैं',roomNA:'कमरा निर्धारित नहीं',doctorAssigned:'नियुक्त डॉक्टर',call:'बुलाया जा रहा है…',select:'इस विभाग के लिए केवल सक्रिय और उपयुक्त डॉक्टर दिखाए गए हैं।'},
 'bn-IN':{ready:'আপনি প্রস্তুত',title:'আপনার টোকেন প্রস্তুত।',help:'পরামর্শের সময় পর্যন্ত এই স্ক্রিনটি সঙ্গে রাখুন।',token:'আপনার টোকেন',doctor:'ডাক্তার',room:'কক্ষ',care:'সেবা',department:'বিভাগ',choose:'অন্য ডাক্তার বেছে নিন',close:'ডাক্তারের তালিকা বন্ধ করুন',available:'উপলব্ধ ডাক্তার',noOther:'আর কোনো উপযুক্ত ডাক্তার পাওয়া যায়নি।',unchanged:'আপনার বর্তমান ডাক্তারই থাকবেন।',home:'হোমে যান',connected:'আপনার ভিজিট যুক্ত আছে।',connectedHelp:'টোকেন, ডাক্তার, ইতিহাস এবং আপলোড করা নথি একই এনকাউন্টারের সঙ্গে যুক্ত।',assigned:'আপনার ডাক্তার এখন',roomNA:'কক্ষ নির্ধারিত নয়',doctorAssigned:'নিযুক্ত ডাক্তার',call:'ডাকা হচ্ছে…',select:'এই বিভাগের জন্য শুধু সক্রিয় ও উপযুক্ত ডাক্তারদের দেখানো হচ্ছে।'},
};

export default function Completion(){
 const auth=useAuth(),nav=useNavigate(),{preferences}=usePatientPreferences(),id=auth.user.id,copy=COPY[preferences.language]||COPY['en-IN'];
 const [encounter,setEncounter]=useState(null),[error,setError]=useState(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 async function load(){
  setError(null);
  try{
   const j=loadJourney(id);
   let encounterId=j.encounterId;
   if(!encounterId){
    const active=await api.activeEncounter(auth.token,id);
    encounterId=active.encounter?.id;
    if(encounterId) saveJourney(id,{encounterId,department:active.encounter.department,doctorId:active.encounter.doctor_id,doctorName:active.encounter.doctor_name,doctorRoom:active.encounter.doctor_room_number});
   }
   if(!encounterId){nav('/patient/visit',{replace:true});return}
   const e=await api.encounter(auth.token,encounterId);
   setEncounter(e.encounter);
   saveJourney(id,{encounterId:e.encounter.id,department:e.encounter.department,doctorId:e.encounter.doctor_id,doctorName:e.encounter.doctor_name,doctorRoom:e.encounter.doctor_room_number,tokenReady:true});
  }catch(e2){setError(e2)}
 }
 useEffect(()=>{load()},[id,auth.token]);
 if(!encounter&&!error)return <Loading label={preferences.language==='hi-IN'?'आपका टोकन तैयार हो रहा है…':preferences.language==='bn-IN'?'আপনার টোকেন প্রস্তুত হচ্ছে…':'Preparing your token…'}/>;
 return <div className="patient-page token-kiosk"><div className="token-success">✓</div><div className="eyebrow">{copy.ready}</div><h1>{copy.title}</h1><p>{copy.help}</p><section className="token-ticket"><span className="token-label">{copy.token}</span><strong className="token-number">A-{String(encounter?.token_number||'').padStart(3,'0')}</strong><div className="token-details"><div><span>{copy.doctor}</span><strong>{encounter?.doctor_name||copy.doctorAssigned}</strong></div><div><span>{copy.room}</span><strong>{encounter?.doctor_room_number||copy.roomNA}</strong></div><div><span>{copy.care}</span><strong>{encounter?.care_type==='ayush'?'AYUSH':preferences.language==='hi-IN'?'सामान्य डॉक्टर':preferences.language==='bn-IN'?'সাধারণ ডাক্তার':'General Doctor'}</strong></div><div><span>{copy.department}</span><strong>{patientDepartmentLabel(encounter?.department||'—',preferences.language)}</strong></div></div></section>{message&&<div className="success-message" role="status">✓ {message}</div>}<ErrorState error={error} onRetry={load}/><div className="token-actions"><button className="btn btn-primary btn-xl" onClick={()=>nav('/patient')}>{copy.home}</button></div><div className="token-note"><span>🔐</span><div><strong>{copy.connected}</strong><p>{copy.connectedHelp}</p></div></div></div>;
}
