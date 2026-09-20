import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { usePatientPreferences } from '../../context/PatientPreferencesContext';
import { ErrorState, Loading } from '../../components/States';
import { LANGUAGES } from '../../utils/constants';
import { loadJourney, saveJourney } from '../../utils/storage';
import { speakQuestion, stopSpeech } from '../../services/voice/speech';

const COPY = {
  'en-IN': { title:'Tell us a little more.', help:'Choose the easiest way to answer. You may skip this question.', tap:'Tap an answer', type:'Speak or type', placeholder:'Type your answer…', skip:'Skip question', next:'Continue', finish:'Finish', back:'Back', height:'Height', weight:'Weight', heightUnit:'cm', weightUnit:'kg', decrease:'Decrease', increase:'Increase', measurements:'Body measurements', measurementsHelp:'Use the + and − buttons. These values are saved with your AYUSH intake.' },
  'hi-IN': { title:'थोड़ा और बताएं।', help:'आसानी से जवाब दें। आप इस सवाल को छोड़ सकते हैं।', tap:'एक जवाब चुनें', type:'बोलें या लिखें', placeholder:'अपना जवाब यहाँ लिखें…', skip:'सवाल छोड़ें', next:'आगे बढ़ें', finish:'पूरा करें', back:'वापस', height:'कद', weight:'वजन', heightUnit:'सेमी', weightUnit:'किग्रा', decrease:'कम करें', increase:'बढ़ाएं', measurements:'शारीरिक माप', measurementsHelp:'+ और − बटन का उपयोग करें। ये मान आपके आयुष रिकॉर्ड के साथ सुरक्षित रहेंगे।' },
  'bn-IN': { title:'আরও একটু বলুন।', help:'যেভাবে সহজ হয় সেভাবে উত্তর দিন। আপনি এই প্রশ্নটি এড়িয়ে যেতে পারেন।', tap:'একটি উত্তর বেছে নিন', type:'কথা বলুন বা লিখুন', placeholder:'আপনার উত্তর এখানে লিখুন…', skip:'প্রশ্ন এড়িয়ে যান', next:'পরবর্তী', finish:'সম্পূর্ণ করুন', back:'ফিরে যান', height:'উচ্চতা', weight:'ওজন', heightUnit:'সেমি', weightUnit:'কেজি', decrease:'কমিয়ে দিন', increase:'বাড়ান', measurements:'শারীরিক মাপ', measurementsHelp:'+ এবং − বোতাম ব্যবহার করুন। এই মানগুলি আপনার আয়ুষ রেকর্ডের সঙ্গে সংরক্ষিত হবে।' },
};

export default function Ayush() {
  const auth=useAuth(), nav=useNavigate(), {preferences}=usePatientPreferences(), id=auth.user.id;
  const copy=COPY[preferences.language]||COPY['en-IN'];
  const eyebrow=preferences.language==='hi-IN'?'आयुष देखभाल':preferences.language==='bn-IN'?'আয়ুষ সেবা':'AYUSH CARE';
  const [data,setData]=useState(null),[index,setIndex]=useState(0),[value,setValue]=useState(''),[selected,setSelected]=useState([]),[responses,setResponses]=useState({}),[busy,setBusy]=useState(false),[error,setError]=useState(null),[speaking,setSpeaking]=useState(false),[measurements,setMeasurements]=useState({height:170,weight:65});

  async function load(){
    setError(null);
    try{
      const r=await api.ayushQuestions(auth.token,preferences.language); setData(r);
      const local=JSON.parse(sessionStorage.getItem(`aarogyasaar.ayush.${id}`)||'{}');
      const stored={...(local.responses||{})}; const i=Math.min(Number(local.index||0),(r.questions?.length||1)-1);
      setResponses(stored); setIndex(i);
      const q=r.questions?.[i]; const v=stored[q?.id];
      if(q?.id==='pramana' && v && typeof v==='object'){setMeasurements({...measurements,...v});setValue('');setSelected([])}
      else {setValue(Array.isArray(v)?'':v||'');setSelected(Array.isArray(v)?v:[])}
    }catch(e){setError(e)}
  }
  useEffect(()=>{load();return()=>stopSpeech()},[preferences.language]);
  const q=data?.questions?.[index];
  useEffect(()=>{if(q?.question&&preferences.audio_enabled){setSpeaking(true);speakQuestion(auth.token,q.question,preferences.language,preferences.audio_speed).finally(()=>setSpeaking(false))}},[q?.id,preferences.language,preferences.audio_enabled]);
  const isMeasurements=q?.type==='measurements';
  const currentAnswer=useMemo(()=>isMeasurements?measurements:(q?.type==='multi'?selected:value),[isMeasurements,measurements,q?.type,selected,value]);
  function toggle(o){setSelected(s=>s.includes(o)?s.filter(x=>x!==o):[...s,o])}
  function changeMeasure(key,delta){const limits={height:[50,250,1],weight:[10,300,0.5]};const [min,max,step]=limits[key];setMeasurements(m=>({...m,[key]:Math.min(max,Math.max(min,Number((m[key]+delta*step).toFixed(1))))}))}
  async function next(skip=false){
    if(!q||busy)return;
    const answer=isMeasurements?measurements:(q.type==='multi'?selected:value);
    if(!skip&&((Array.isArray(answer)&&!answer.length)||(!Array.isArray(answer)&&(!String(answer).trim()))))return;
    stopSpeech();setBusy(true);
    try{
      const sessionId=loadJourney(id).ayushSessionId||`ayush-${id}-${Date.now()}`;saveJourney(id,{ayushSessionId:sessionId});
      const storedAnswer=isMeasurements?answer:answer;
      const nextResponses={...responses,[q.id]:skip?'':storedAnswer};
      const r=await api.ayushAnswer(auth.token,{patient_id:id,session_id:sessionId,question_id:q.id,answer:isMeasurements?JSON.stringify(storedAnswer):Array.isArray(answer)?answer.join(', '):String(skip?'':answer),skipped:skip,answers:nextResponses,language:preferences.language});
      setResponses(nextResponses);sessionStorage.setItem(`aarogyasaar.ayush.${id}`,JSON.stringify({responses:nextResponses,index:index+1}));
      if(r.completed){
        const complete=await api.ayushComplete(auth.token,{patient_id:id,session_id:sessionId,responses:nextResponses,language:preferences.language});
        if(!complete?.consultation_id) throw new Error('AYUSH handoff was not created.');
        saveJourney(id,{ayushComplete:true});nav('/patient/documents',{replace:true});return;
      }
      setIndex(index+1);const nq=r.next_question;const nv=nextResponses[nq?.id];
      if(nq?.id==='pramana'&&nv&&typeof nv==='object'){setMeasurements({...measurements,...nv});setValue('');setSelected([])}else{setValue(Array.isArray(nv)?'':nv||'');setSelected(Array.isArray(nv)?nv:[])}
    }catch(e){setError(e)}finally{setBusy(false)}
  }
  if(!data)return <Loading label={preferences.language==='hi-IN'?'आपके सवाल तैयार हो रहे हैं…':preferences.language==='bn-IN'?'আপনার প্রশ্ন প্রস্তুত হচ্ছে…':'Preparing your questions…'}/>;
  return <div className="patient-page interview-kiosk">
    <div className="interview-kiosk-head"><div><div className="eyebrow">{eyebrow}</div><div className="eyebrow">{preferences.language==='hi-IN'?`सवाल ${index+1} / ${data.questions.length}`:preferences.language==='bn-IN'?`প্রশ্ন ${index+1} / ${data.questions.length}`:`QUESTION ${index+1} OF ${data.questions.length}`}</div><h1>{copy.title}</h1><p>{copy.help}</p></div><div className="language-chip">{LANGUAGES[preferences.language]}</div></div>
    <ErrorState error={error} onRetry={load}/>
    <section className="question-card-large"><button type="button" className="hear-question" onClick={()=>{setSpeaking(true);speakQuestion(auth.token,q?.question||'',preferences.language,preferences.audio_speed).finally(()=>setSpeaking(false))}} disabled={speaking}>🔊 {speaking?(preferences.language==='hi-IN'?'बोल रहे हैं…':preferences.language==='bn-IN'?'বলা হচ্ছে…':'Speaking…'):(preferences.language==='hi-IN'?'सवाल सुनें':preferences.language==='bn-IN'?'প্রশ্ন শুনুন':'Hear question')}</button><div className="question-icon">🌿</div><h2>{q?.question}</h2><p className="question-help">{q?.hint}</p></section>
    {isMeasurements?<section className="card ayush-measurements"><div className="answer-mode-title"><strong>{copy.measurements}</strong><span>{copy.measurementsHelp}</span></div><div className="measurement-grid">{[['height',copy.height,copy.heightUnit],['weight',copy.weight,copy.weightUnit]].map(([key,label,unit])=><div className="measurement-control" key={key}><strong>{label}</strong><div className="measurement-row"><button type="button" aria-label={copy.decrease} onClick={()=>changeMeasure(key,-1)} disabled={busy}>−</button><output>{measurements[key]} {unit}</output><button type="button" aria-label={copy.increase} onClick={()=>changeMeasure(key,1)} disabled={busy}>+</button></div></div>)}</div></section>:q?.options?.length>0&&<section className="answer-card-section"><div className="answer-mode-title"><strong>{copy.tap}</strong><span>{preferences.language==='hi-IN'?'एक विकल्प चुनें':preferences.language==='bn-IN'?'একটি বিকল্প বেছে নিন':'Choose one'}</span></div><div className="context-answer-grid">{q.options.map(o=><button key={o} type="button" className={`context-answer ${(q.type==='multi'?selected.includes(o):value===o)?'selected':''}`} onClick={()=>q.type==='multi'?toggle(o):setValue(o)}>{o}</button>)}</div></section>}
    {!isMeasurements&&<section className="type-answer-section"><div className="answer-mode-title"><strong>{copy.type}</strong></div><textarea value={value} onChange={e=>setValue(e.target.value)} rows="4" placeholder={copy.placeholder}/><div className="three-mode-actions"><button className="btn btn-light btn-xl" onClick={()=>next(true)} disabled={busy}>{copy.skip}</button><button className="btn btn-primary btn-xl" onClick={()=>next(false)} disabled={busy}>{busy?(preferences.language==='hi-IN'?'सहेजा जा रहा है…':preferences.language==='bn-IN'?'সংরক্ষণ হচ্ছে…':'Saving…'):index===data.questions.length-1?copy.finish:copy.next} →</button></div></section>}
    {isMeasurements&&<div className="three-mode-actions"><button className="btn btn-light btn-xl" onClick={()=>next(true)} disabled={busy}>{copy.skip}</button><button className="btn btn-primary btn-xl" onClick={()=>next(false)} disabled={busy}>{busy?(preferences.language==='hi-IN'?'सहेजा जा रहा है…':preferences.language==='bn-IN'?'সংরক্ষণ হচ্ছে…':'Saving…'):index===data.questions.length-1?copy.finish:copy.next} →</button></div>}
    <div className="bottom-action"><button type="button" className="btn btn-outline btn-xl" onClick={()=>{if(index===0){nav('/patient/ayush-transition');return;} const previousIndex=Math.max(0,index-1); const previous=data.questions?.[previousIndex]; setIndex(previousIndex); const pv=responses[previous?.id]; if(previous?.id==='pramana'&&pv&&typeof pv==='object'){setMeasurements({...measurements,...pv});setValue('');setSelected([])}else{setValue(Array.isArray(pv)?'':pv||'');setSelected(Array.isArray(pv)?pv:[])}}}>← {copy.back}</button></div>
  </div>;
}
