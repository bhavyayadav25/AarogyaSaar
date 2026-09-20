import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { patientText } from '../utils/patientText';
import { useAuth } from '../context/AuthContext';
import { isRecognitionSupported, startRecognition, stopRecognition } from '../services/voice/recognition';

const COPY={
 'en-IN':{unsupported:'Voice input is not supported here. You can type your answer instead.',permission:'Microphone permission was denied. Allow microphone access and try again.',recording:'Listening… tap to stop',processing:'Converting your answer to text…',failed:'Voice input could not be completed. Please try again or enter your answer manually.',retry:'Try again',manual:'Enter manually'},
 'hi-IN':{unsupported:'इस डिवाइस पर आवाज़ से जवाब देना उपलब्ध नहीं है। आप जवाब लिख सकते हैं।',permission:'माइक्रोफ़ोन की अनुमति नहीं मिली। अनुमति दें और फिर कोशिश करें।',recording:'सुन रहे हैं… रोकने के लिए दबाएं',processing:'आपका जवाब टेक्स्ट में बदला जा रहा है…',failed:'आवाज़ से जवाब पूरा नहीं हो सका। फिर कोशिश करें या जवाब लिखें।',retry:'फिर कोशिश करें',manual:'खुद लिखें'},
 'bn-IN':{unsupported:'এই ডিভাইসে ভয়েস ইনপুট নেই। আপনি উত্তর লিখতে পারেন।',permission:'মাইক্রোফোনের অনুমতি পাওয়া যায়নি। অনুমতি দিয়ে আবার চেষ্টা করুন।',recording:'শুনছি… থামাতে চাপুন',processing:'আপনার উত্তর টেক্সটে বদলানো হচ্ছে…',failed:'ভয়েস ইনপুট সম্পূর্ণ করা যায়নি। আবার চেষ্টা করুন বা উত্তর লিখুন।',retry:'আবার চেষ্টা করুন',manual:'নিজে লিখুন'}
};

function pickMimeType(){
  if(typeof MediaRecorder==='undefined')return '';
  const choices=['audio/webm;codecs=opus','audio/webm','audio/mp4','audio/ogg;codecs=opus'];
  return choices.find(x=>MediaRecorder.isTypeSupported?.(x))||'';
}

export default function VoiceInput({language='en-IN',onText,label,className='',patientId,sessionId}){
 const auth=useAuth();
 const copy=COPY[language]||COPY['en-IN'];
 const text=patientText(language);
 const [state,setState]=useState('idle'),[message,setMessage]=useState('');
 const recorderRef=useRef(null),streamRef=useRef(null),chunksRef=useRef([]),mountedRef=useRef(true),callbackRef=useRef(onText),recognitionRef=useRef(false),browserFallbackTimerRef=useRef(null),browserGotResultRef=useRef(false);

 useEffect(()=>{callbackRef.current=onText},[onText]);
 useEffect(()=>()=>{
   mountedRef.current=false;
   if(browserFallbackTimerRef.current){clearTimeout(browserFallbackTimerRef.current);browserFallbackTimerRef.current=null;}
   stopRecognition();
   try{recorderRef.current?.stop()}catch{}
   streamRef.current?.getTracks?.().forEach(t=>t.stop());
 },[]);

 function fail(kind='failed'){
   if(!mountedRef.current)return;
   setState('idle');
   setMessage(kind==='permission'?copy.permission:copy.failed);
 }

 function deliver(value){
   const transcript=String(value||'').replace(/\s+/g,' ').trim();
   if(!transcript||!mountedRef.current)return;
   // This is the single handoff into Interview.jsx.  It is intentionally
   // called for interim and final browser results so the controlled textarea
   // shows speech immediately instead of waiting for microphone shutdown.
   callbackRef.current?.(transcript);
 }

 function beginBrowser(){
   if(!isRecognitionSupported()) return false;
   browserGotResultRef.current=false;
   if(browserFallbackTimerRef.current){clearTimeout(browserFallbackTimerRef.current);browserFallbackTimerRef.current=null;}
   setMessage('');
   setState('recording');
   recognitionRef.current=true;
   const started=startRecognition(language,(event)=>{
     if(!mountedRef.current)return;
     if(event.state==='listening'||event.state==='restarting'){
       setState('recording');
       if(event.state==='listening'){
         setMessage('');
         if(browserFallbackTimerRef.current)clearTimeout(browserFallbackTimerRef.current);
         browserFallbackTimerRef.current=setTimeout(()=>{
           if(!mountedRef.current||browserGotResultRef.current||!recognitionRef.current)return;
           recognitionRef.current=false;
           stopRecognition();
           setState('starting');
           setMessage(copy.processing);
           beginRecorder();
         },5000);
       }
       return;
     }
     if((event.state==='interim'||event.state==='result')&&event.text){
       browserGotResultRef.current=true;
       if(browserFallbackTimerRef.current){clearTimeout(browserFallbackTimerRef.current);browserFallbackTimerRef.current=null;}
       deliver(event.text);
       return;
     }
     if(event.state==='stopped'){
       recognitionRef.current=false;
       setState('idle');
       setMessage('');
       return;
     }
     if(event.state==='error'){
       recognitionRef.current=false;
       if(event.error==='permission'){
         setState('idle');setMessage(copy.permission);
       }else if(event.error==='network'&&event.recoverable){
         stopRecognition();
         setState('starting');
         setMessage(copy.processing);
         beginRecorder();
       }else if(event.error==='start-failed'&&event.recoverable){
         setState('starting');
         beginRecorder();
       }else{
         setState('idle');setMessage(copy.failed);
       }
     }
     if(event.state==='unsupported'){
       recognitionRef.current=false;
       setState('idle');setMessage(copy.unsupported);
     }
   });
   if(!started){recognitionRef.current=false;setState('idle');return false;}
   return true;
 }

 async function finishRecorder(blob){
   if(!mountedRef.current)return;
   setState('processing');setMessage(copy.processing);
   try{
     const fd=new FormData();
     fd.append('audio',blob,blob.type.includes('mp4')?'answer.mp4':'answer.webm');
     if(patientId!=null)fd.append('patient_id',String(patientId));
     if(sessionId)fd.append('session_id',String(sessionId));
     fd.append('language',language);
     const result=await api.transcribe(auth.token,fd);
     const transcript=String(result?.transcript||'').replace(/\s+/g,' ').trim();
     if(!transcript)throw new Error('empty transcript');
     deliver(transcript);
     if(mountedRef.current){setState('idle');setMessage('');}
   }catch(e){
     if(mountedRef.current){
       setState('idle');
       setMessage(e?.status===503?(language==='hi-IN'?'आवाज़ की सेवा अभी उपलब्ध नहीं है। जवाब लिखें या माइक्रोफ़ोन से फिर कोशिश करें।':language==='bn-IN'?'ভয়েস সেবা এখন পাওয়া যাচ্ছে না। উত্তর লিখুন বা মাইক্রোফোন দিয়ে আবার চেষ্টা করুন।':'Voice transcription service is unavailable. Please type your answer or try the microphone again.'):copy.failed);
     }
   }finally{
     streamRef.current?.getTracks?.().forEach(t=>t.stop());
     streamRef.current=null;recorderRef.current=null;
   }
 }

 async function beginRecorder(){
   if(typeof navigator==='undefined'||!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined'){
     setState('idle');setMessage(copy.unsupported);return;
   }
   try{
     const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
     if(!mountedRef.current){stream.getTracks().forEach(t=>t.stop());return;}
     streamRef.current=stream;chunksRef.current=[];
     const mimeType=pickMimeType();
     const r=mimeType?new MediaRecorder(stream,{mimeType}):new MediaRecorder(stream);
     recorderRef.current=r;
     r.ondataavailable=e=>{if(e.data?.size)chunksRef.current.push(e.data)};
     r.onerror=()=>fail();
     r.onstop=()=>{
       stream.getTracks().forEach(t=>t.stop());
       const blob=new Blob(chunksRef.current,{type:r.mimeType||mimeType||'audio/webm'});
       chunksRef.current=[];
       if(blob.size)finishRecorder(blob);else fail();
     };
     r.start(250);
     setState('recording');setMessage(copy.recording);
   }catch(e){
     streamRef.current?.getTracks?.().forEach(t=>t.stop());
     fail(e?.name==='NotAllowedError'?'permission':'failed');
   }
 }

 function start(){setState('starting');if(!beginBrowser())beginRecorder();}
 function stop(){
   if(browserFallbackTimerRef.current){clearTimeout(browserFallbackTimerRef.current);browserFallbackTimerRef.current=null;}
   if(recognitionRef.current){
     // Keep the recognizer session alive until its onend callback. A final
     // onresult can arrive after stop(), and that result must still reach the
     // controlled patient answer input before we return to idle.
     setState('processing');
     setMessage(copy.processing);
     stopRecognition();
     return;
   }
   const r=recorderRef.current;
   if(r&&r.state!=='inactive'){
     setState('processing');
     try{r.stop()}catch{fail();}
   }
 }
 function toggle(){if(state==='recording')stop();else if(state==='idle')start();}
 const busy=state==='processing'||state==='starting';
 const buttonLabel=state==='recording'?copy.recording:(label||text.speak);
 return <div className={`voice-input ${className}`}>
   <button type="button" className={`voice-input-button ${state==='recording'?'recording':''}`} onClick={toggle} disabled={busy} aria-label={buttonLabel} aria-pressed={state==='recording'}>
     <span aria-hidden="true">🎤</span><strong>{busy?copy.processing:buttonLabel}</strong>
   </button>
   {message&&<div className="voice-input-message" role="status" aria-live="polite">{message}</div>}
   {message&&state==='idle'&&<div className="voice-input-recovery"><button type="button" className="btn btn-light" onClick={()=>{setMessage('');start()}}>{copy.retry}</button><span>{copy.manual}</span></div>}
 </div>;
}
