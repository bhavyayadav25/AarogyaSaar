import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { usePatientPreferences } from '../../context/PatientPreferencesContext';
import { ErrorState, Loading } from '../../components/States';
import { LANGUAGES } from '../../utils/constants';
import { loadJourney, saveJourney } from '../../utils/storage';
import { patientText, interviewOptionLabel } from '../../utils/patientText';
import { speakQuestion, stopSpeech } from '../../services/voice/speech';

const CARD_RULES = {
 chief_complaint:[['Fever','fever'],['Pain','pain'],['Cough / Cold','cough'],['Weakness','weakness'],['Stomach problem','stomach pain'],['Headache','headache'],['Breathing problem','breathing problem'],['Injury','injury'],['Other','other']],
 onset:[['Today','today'],['A few days','few days'],['1–2 weeks','1-2 weeks'],['More than 2 weeks','more than 2 weeks']],
 location:[['Head','head'],['Chest','chest'],['Stomach','stomach'],['Back','back'],['Arm','arm'],['Leg','leg'],['Joint','joint'],['Skin','skin'],['Other','other']],
 severity:[['Mild','mild'],['Moderate','moderate'],['Severe','severe'],['Not sure','not sure']],
 character:[['Sharp','sharp'],['Burning','burning'],['Throbbing','throbbing'],['Tight / pressure','tight or pressure'],['Heavy','heavy'],['Other','other']],
 chest_radiation:[['No','no'],['Arm / shoulder','arm or shoulder'],['Jaw / neck','jaw or neck'],['Back','back'],['Not sure','not sure']],
 chest_exertion:[['Worse with activity','worse with activity'],['Better with rest','better with rest'],['No change','no change'],['Not sure','not sure']],
 chest_breathlessness:[['Breathlessness','breathlessness'],['Sweating','sweating'],['Dizziness','dizziness'],['Fainting','fainting'],['Heart racing','heart racing'],['None of these','none of these']],
 headache_visual:[['Blurred vision','blurred vision'],['Weakness / numbness','weakness or numbness'],['Speech trouble','difficulty speaking'],['Walking trouble','trouble walking'],['None of these','none of these']],
 headache_nausea:[['Nausea','nausea'],['Vomiting','vomiting'],['Light sensitivity','sensitive to light'],['Sound sensitivity','sensitive to sound'],['None of these','none of these']],
 headache_trigger:[['Exertion','exertion'],['Coughing','coughing'],['Poor sleep','lack of sleep'],['Stress','stress'],['Recent injury','recent injury'],['None','none']],
 abdominal_food:[['Worse after food','worse after food'],['Better after stool','better after stool'],['Changes with medicine','changes with medicine'],['No change','no change']],
 abdominal_bowel:[['Vomiting','vomiting'],['Diarrhea','diarrhea'],['Constipation','constipation'],['Blood / black stool','blood or black stool'],['None of these','none of these']],
 abdominal_urinary:[['Burning urine','burning urine'],['Blood in urine','blood in urine'],['Pain to back / groin','pain to back or groin'],['None of these','none of these']],
 fever_pattern:[['Below 100°F','below 100'],['100–102°F','100–102'],['102–104°F','102–104'],['Above 104°F','above 104'],['Not measured','not measured']],
 fever_infection:[['Cough','cough'],['Sore throat','sore throat'],['Breathing trouble','breathing difficulty'],['Vomiting','vomiting'],['Diarrhea','diarrhea'],['Burning urine','burning urine'],['None of these','none of these']],
 respiratory_cough:[['Dry cough','dry cough'],['Cough with phlegm','phlegm'],['Blood in phlegm','blood in phlegm'],['No cough','no cough']],
 respiratory_activity:[['Worse with activity','worse with activity'],['Worse lying down','worse lying down'],['Worse at night','worse at night'],['Sudden','sudden'],['Gradual','gradual']],
 respiratory_wheeze:[['Wheezing','wheezing'],['Chest tightness','chest tightness'],['Fever','fever'],['Known asthma','asthma'],['None of these','none of these']],
 general_change:[['Better with rest','better with rest'],['Worse with activity','worse with activity'],['Medicine helped','medicine helped'],['No change','no change']],
 general_impact:[['Sleep affected','sleep affected'],['Eating affected','eating affected'],['Work affected','work affected'],['Movement affected','movement affected'],['No major effect','no major effect']],
 associated:[['Fever','fever'],['Cough','cough'],['Breathing problem','breathing difficulty'],['Vomiting','vomiting'],['Dizziness','dizziness'],['None of these','none of these']],
 past_history:[['No known illness','no known illness'],['Diabetes','diabetes'],['High blood pressure','high blood pressure'],['Heart disease','heart disease'],['Asthma','asthma'],['Other','other']],
 medications:[['No medicines','no medicines'],['Prescription medicines','prescription medicines'],['Over-the-counter medicines','over-the-counter medicines'],['Supplements','supplements'],['Not sure','not sure']],
 allergies:[['No known allergies','no known allergies'],['Medicine allergy','medicine allergy'],['Food allergy','food allergy'],['Other allergy','other allergy'],['Not sure','not sure']],
 family_history:[['No major family history','none known'],['Diabetes','diabetes'],['High blood pressure','high blood pressure'],['Heart disease','heart disease'],['Asthma','asthma'],['Other','other']],
 personal_history:[['No major concern','none'],['Tobacco','tobacco'],['Alcohol','alcohol'],['Sleep problem','sleep'],['Stress','stress'],['Other','other']],
 review_systems:[['Fever','fever'],['Breathing problem','breathing difficulty'],['Chest discomfort','chest discomfort'],['Vomiting','vomiting'],['Urinary change','urinary change'],['Dizziness','dizziness'],['None of these','none of these']],
};

function makeId(){return globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random().toString(16).slice(2)}`;}
export default function Interview(){
 const auth=useAuth(),nav=useNavigate(),[searchParams]=useSearchParams(),{preferences}=usePatientPreferences(),patientId=auth.user.id;
 const rewind = searchParams.get('rewind') === '1';
 const text = patientText(preferences.language);
 const [sessionId,setSessionId]=useState(''),[question,setQuestion]=useState(null),[state,setState]=useState(null),[number,setNumber]=useState(1),[total,setTotal]=useState(0),[answer,setAnswer]=useState(''),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(null),[speaking,setSpeaking]=useState(false),[answerMode,setAnswerMode]=useState('text');
 const spokenRef=useRef('');
 async function load(){setLoading(true);setError(null);try{const j=loadJourney(patientId);const sid=j.sessionId||makeId();const language=preferences.language||'en-IN';saveJourney(patientId,{sessionId:sid,language,interviewStarted:true});setSessionId(sid);let existing=null;try{existing=await api.interviewState(auth.token,patientId,sid)}catch(e){if(e.status!==404)throw e}if(existing){if(existing.status==='completed' && rewind){const rewound=await api.interviewBack(auth.token,{patient_id:patientId,session_id:sid});saveJourney(patientId,{interviewComplete:false,documentsComplete:false});setState(rewound);setQuestion(rewound.current_question);setNumber(Math.max(1,(rewound.answered_question_ids?.length||0)+1));setTotal(0);}else{setState(existing);setQuestion(existing.current_question);setNumber((existing.answered_question_ids?.length||0)+1);setTotal(0);if(existing.status==='completed'){saveJourney(patientId,{interviewComplete:true,documentsComplete:false});nav('/patient/ayush-transition',{replace:true});return}}}else{const r=await api.interviewQuestions(auth.token,patientId,language,sid);setState(r);setQuestion(r.question);setNumber(1);setTotal(r.total_questions||0)}}catch(e){setError(e)}finally{setLoading(false)}}
 const loadKeyRef=useRef('');
 useEffect(()=>{
  let cancelled=false;
  const loadKey=`${patientId}|${preferences.language||'en-IN'}|${rewind?'rewind':'resume'}`;
  // React StrictMode can mount the effect twice in development. Reuse the
  // same session/load rather than issuing a second navigation-triggering
  // request for the same patient, language and interview mode.
  if(loadKeyRef.current===loadKey)return;
  loadKeyRef.current=loadKey;
  (async()=>{if(cancelled)return; await load();})();
  return()=>{cancelled=true;stopSpeech()};
 },[patientId,preferences.language,rewind]);
 async function speak(force=false){if(!question?.text||!preferences.audio_enabled)return;const key=`${question.id}|${preferences.language}`;if(!force&&spokenRef.current===key)return;spokenRef.current=key;setSpeaking(true);try{await speakQuestion(auth.token,question.text,preferences.language,preferences.audio_speed)}catch{setVoiceNote(text.voiceUnavailable)}finally{setSpeaking(false)}}
 useEffect(()=>{if(!loading&&question) speak(false)},[question?.id,question?.text,preferences.language,preferences.audio_enabled]);
 async function submit(value=answer,skipped=false){const text=String(value||'').trim();if(!question||busy||(!text&&!skipped))return;stopSpeech();spokenRef.current='';setBusy(true);setError(null);try{const r=await api.interviewAnswer(auth.token,{patient_id:patientId,session_id:sessionId,question_id:question.id,answer:text,skipped,answers:state?.structured||{},language:preferences.language,input_mode:skipped?'skipped':answerMode});setState(r.state);setAnswer('');setAnswerMode('text');setNumber(r.question_number||number+1);setTotal(r.total_questions||total);if(r.completed){saveJourney(patientId,{interviewComplete:true,ayushComplete:false,ayushSkipped:false,documentsComplete:false});nav('/patient/ayush-transition',{replace:true});return}setQuestion(r.next_question)}catch(e){setError(e)}finally{setBusy(false)}}
 async function back(){if(busy)return;stopSpeech();setError(null);setBusy(true);try{const r=await api.interviewBack(auth.token,{patient_id:patientId,session_id:sessionId});setState(r);setQuestion(r.current_question);setAnswer(r.structured?.[r.current_question_id]||'');setNumber(Math.max(1,(r.answered_question_ids?.length||0)+1))}catch(e){if(e.status===409)nav('/patient/visit');else setError(e)}finally{setBusy(false)}}
 const cards=useMemo(()=>CARD_RULES[question?.id]||[],[question?.id]); const localizedCards=cards.map(([label,value])=>[interviewOptionLabel(label,preferences.language),value]);
 const progress=total?Math.min(100,Math.max(0,(number/total)*100)):0;
 const hasAnswer=Boolean(answer.trim());
 function chooseCard(value){setAnswer(value);setAnswerMode('card');}
 if(loading)return <Loading label={text.loadingInterview}/>;
 return <div className="patient-page interview-kiosk">
  <div className="interview-progress-wrap" aria-label={total?`Question ${number} of ${total}`:`Question ${number}`}>
    <div className="interview-progress-top"><span>{preferences.language==='hi-IN'?`सवाल ${number}${total?` / ${total}`:''}`:preferences.language==='bn-IN'?`প্রশ্ন ${number}${total?` / ${total}`:''}`:`QUESTION ${number}${total?` OF ${total}`:''}`}</span><span>{LANGUAGES[preferences.language]}</span></div>
    <div className="interview-progress-track"><span style={{width:`${progress}%`}} /></div>
  </div>
  <div className="interview-kiosk-head"><div><div className="eyebrow">{text.interviewTitle}</div><h1>{text.interviewHelp}</h1></div></div><ErrorState error={error} onRetry={load}/>
  <section className="question-card-large patient-question-focus" aria-live="polite"><button type="button" className={`hear-question ${speaking?'active':''}`} onClick={()=>speak(true)} disabled={speaking}>{speaking?'🔊 '+text.speaking:'🔊 '+text.hear}</button><div className="question-icon">💬</div><h2>{question?.text}</h2><p className="question-hint">{preferences.language==='hi-IN'?'नीचे लिखें या एक विकल्प चुनें।':preferences.language==='bn-IN'?'নিচে লিখুন অথবা একটি বিকল্প বেছে নিন।':'Type or choose an option below.'}</p></section>
  {localizedCards.length>0&&<section className="answer-card-section"><div className="answer-mode-title"><strong>{text.tapAnswer}</strong><span>{text.chooseOne}</span></div><div className="context-answer-grid">{localizedCards.map(([label,value])=><button type="button" key={`${question.id}-${value}`} className={`context-answer ${answer===value?'selected':''}`} onClick={()=>chooseCard(value)} disabled={busy}><span>{label}</span>{answer===value&&<b aria-hidden="true">✓</b>}</button>)}</div></section>}
  <section className="type-answer-section patient-answer-panel"><div className="answer-mode-title"><strong>{preferences.language==='hi-IN'?'अपना जवाब लिखें':preferences.language==='bn-IN'?'আপনার উত্তর লিখুন':'Type your answer'}</strong><span>{text.savedWith}</span></div><div className="patient-textarea-wrap"><textarea aria-label={text.type} value={answer} onChange={e=>{setAnswer(e.target.value);setAnswerMode('text')}} rows="4" placeholder={text.type} disabled={busy}/>{hasAnswer&&<button type="button" className="clear-answer" onClick={()=>{setAnswer('');setAnswerMode('text')}} disabled={busy}>×</button>}</div><div className="answer-meta"><span>{hasAnswer?'✓ '+(preferences.language==='hi-IN'?'जवाब तैयार है':preferences.language==='bn-IN'?'উত্তর প্রস্তুত':'Answer ready'):''}</span><span>{answer.length>0?`${answer.length}`:''}</span></div><div className="three-mode-actions"><button type="button" className="btn btn-light btn-xl" onClick={()=>submit('',true)} disabled={busy}>{text.skip}</button><button type="button" className="btn btn-primary btn-xl" onClick={()=>submit()} disabled={!hasAnswer||busy}>{busy?(preferences.language==='hi-IN'?'सहेजा जा रहा है…':preferences.language==='bn-IN'?'সংরক্ষণ হচ্ছে…':'Saving…'):text.continue} →</button></div></section>
  <div className="bottom-action"><button type="button" className="btn btn-outline btn-xl" onClick={back} disabled={busy}>← {text.back}</button></div>
 </div>;
}
