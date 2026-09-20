import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { ErrorState, Loading, Pill, Section } from '../../components/States';
import { speakText, stopSpeech } from '../../services/voice/speech';

const EMPTY={history:'',examination:'',assessment:'',diagnosis:'',plan:'',prescription:'',follow_up:''};
const labels={history:'History',examination:'Examination',assessment:'Assessment',diagnosis:'Diagnosis',plan:'Plan',prescription:'Prescription',follow_up:'Follow-up'};
function priorityLabel(p){return p==='emergency'||p==='urgent'?'HIGH':p==='normal'?'LOW':'MEDIUM'}
function textValue(v){if(v===null||v===undefined||v==='')return 'Not available';if(Array.isArray(v))return v.join(', ');if(typeof v==='object')return Object.entries(v).map(([k,x])=>`${k}: ${textValue(x)}`).join(' · ');return String(v)}
function formatDate(v){if(!v)return 'Not available';try{return new Date(v).toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'})}catch{return v}}
function FactGrid({items}){return <div className="summary-fact-grid">{items.map(([k,v])=><div key={k}><span>{k}</span><strong>{textValue(v)}</strong></div>)}</div>}
function ListBlock({items,empty='Not available'}){return items?.length?<ul className="summary-bullet-list">{items.map((x,i)=><li key={`${String(x)}-${i}`}>{textValue(x)}</li>)}</ul>:<p className="muted">{empty}</p>}
function BriefSection({title,provenance,children,className=''}){return <section className={`brief-section ${className}`.trim()}><div className="brief-section-heading"><h3>{title}</h3>{provenance&&<span className="brief-provenance">{provenance}</span>}</div>{children}</section>}
function briefItems(section){return Array.isArray(section?.items)&&section.items.length?section.items:['Not reported']}
function safetyLevel(flags,severity){if(String(severity).toLowerCase()==='emergency')return 'emergency';if(String(severity).toLowerCase()==='urgent'||flags.length)return 'urgent';return 'none'}
function safetyTitle(flags,severity,status){const level=safetyLevel(flags,severity);if(level==='emergency')return 'Emergency-level warning signals recorded';if(level==='urgent')return 'Safety warning signals recorded';if(status==='complete')return 'Safety assessment completed';return 'Safety assessment incomplete'}

export default function Encounter(){
 const {encounterId}=useParams(),auth=useAuth(),nav=useNavigate();
 const [workspace,setWorkspace]=useState(null),[record,setRecord]=useState(null),[summary,setSummary]=useState(null),[gate,setGate]=useState(null),[docs,setDocs]=useState([]),[sections,setSections]=useState(EMPTY),[notes,setNotes]=useState(''),[review,setReview]=useState('Pending'),[error,setError]=useState(null),[busy,setBusy]=useState(false),[saving,setSaving]=useState(false),[speaking,setSpeaking]=useState(false),[summaryLang,setSummaryLang]=useState('en-IN'),[voiceMessage,setVoiceMessage]=useState('');
 async function load(){
  setError(null);
  try{
   const response=await api.doctorWorkspace(auth.token,encounterId);
   const ws=response.workspace||{};
   const cs=Array.isArray(ws.consultations)?ws.consultations:[];
   setWorkspace(response);
   setDocs(Array.isArray(ws.documents)?ws.documents:[]);

   // The patient handoff consultation is the source for the doctor brief.
   // If an older record has no cached ai_summary, use the existing backend
   // summary endpoint to generate it from that same consultation instead of
   // inventing data or creating a second summary record.
   const general=ws.general_consultation||cs.find(c=>(c.consultation_type==='handoff' || !c.consultation_type) && c.care_type==='allopathy' && c.title!=='AYUSH / Ayurveda intake');
   const clinical=cs.find(c=>c.consultation_type==='clinician' || c.title==='Clinical consultation');
   const summarySource=general;
   const summaryPromise=summarySource?.ai_summary
     ? Promise.resolve({ai_summary:summarySource.ai_summary})
     : summarySource?.id
       ? api.aiSummary(auth.token,summarySource.id)
       : Promise.resolve(null);
   const recordPromise=clinical?.id?api.consultationRecord(auth.token,clinical.id):Promise.resolve(null);
   const gatePromise=clinical?.id?api.clinicalGate(auth.token,clinical.id):Promise.resolve({clinical_gate:ws.clinical_gate||null});
   const [summaryResult,recordResult,gateResult]=await Promise.all([summaryPromise,recordPromise,gatePromise]);
   setSummary(summaryResult?.ai_summary||summarySource?.ai_summary||null);
   if(recordResult?.consultation){
     setRecord(recordResult.consultation);
     setSections({...EMPTY,...(recordResult.consultation.sections||{})});
     setNotes(recordResult.consultation.doctor_notes||'');
     setReview(recordResult.consultation.doctor_review||'Pending');
   }else{
     setRecord(null);setSections(EMPTY);setNotes('');setReview('Pending');
   }
   setGate(gateResult?.clinical_gate||ws.clinical_gate||null);
  }catch(e){setError(e)}
 }
 useEffect(()=>{load();return()=>stopSpeech()},[encounterId]);
 async function call(){setBusy(true);try{await api.updateEncounterStatus(auth.token,encounterId,{status:'called'});await load()}catch(e){setError(e)}finally{setBusy(false)}}
 async function start(){setBusy(true);try{await api.startConsultation(auth.token,encounterId,{encounter_id:+encounterId,title:'Clinical consultation'});await load()}catch(e){setError(e)}finally{setBusy(false)}}
 async function save(){if(!record)return;setSaving(true);try{await api.updateConsultation(auth.token,record.consultation_id,{sections,doctor_notes:notes});await api.reviewConsultation(auth.token,record.consultation_id,{doctor_review:review,doctor_notes:notes});await load()}catch(e){setError(e)}finally{setSaving(false)}}
 async function setReviewStatus(next){if(!record)return;setSaving(true);setError(null);try{await api.reviewConsultation(auth.token,record.consultation_id,{doctor_review:next,doctor_notes:notes});setReview(next);await load()}catch(e){setError(e)}finally{setSaving(false)}}
 async function complete(){if(!record)return;setSaving(true);try{await api.completeConsultation(auth.token,record.consultation_id,{sections,doctor_notes:notes,doctor_review:review||'Completed'});await load()}catch(e){setError(e)}finally{setSaving(false)}}
 async function readSummary(){if(!summary)return;setSpeaking(true);setVoiceMessage('');try{await speakText(auth.token,summary.thirty_second_summary||summary.clinical_summary||'',summaryLang,'1.0')}catch{setVoiceMessage('Voice playback is unavailable.')}finally{setSpeaking(false)}}
 if(!workspace&&!error)return <Loading label="Opening the assigned encounter…"/>;if(!workspace)return <div className="doctor-page"><ErrorState error={error} onRetry={load}/></div>;
 const w=workspace.workspace||{},p=w.patient||{},e=w.encounter||{},cs=w.consultations||[],general=w.general_consultation||cs.find(c=>(c.consultation_type==='handoff'||(!c.consultation_type&&c.title!=='Clinical consultation'&&c.title!=='AYUSH / Ayurveda intake'))&&c.care_type==='allopathy')||{},structured=general.structured||{},risk=w.risk_assessment||{},brief=summary?.brief_sections||{},safety=brief.safety||summary?.safety||{},flagsRaw=safety.alerts||general.red_flags||risk.alerts||[],flags=(Array.isArray(flagsRaw)?flagsRaw:[]).map((f,i)=>typeof f==='string'?{id:`flag-${i}`,label:f,message:'Patient-reported safety signal requiring clinician review.'}:f),severity=summary?.safety?.severity||risk.severity_level||'not_assessed',safetyStatus=safety.status||risk.assessment_status||'incomplete',safetyLevelValue=safetyLevel(flags,severity),careType=e.care_type||'allopathy',ayush=(w.ayush_assessments||[])[0];
 return <div className="doctor-page encounter-page">
  <div className="encounter-head"><button className="back-button" onClick={()=>nav('/doctor')}>← Queue</button><div className="encounter-title"><div className="patient-avatar">{p.name?.slice(0,1)}</div><div><div className="eyebrow">ENCOUNTER #{e.id}</div><h1>{p.name}</h1><p>{p.age??'Age not recorded'} years · {careType==='ayush'?'AYUSH':'General Doctor'} · {e.department}</p></div></div><Pill value={e.status}/></div>
  <ErrorState error={error} onRetry={load}/>
  <div className="encounter-grid"><main>
   <Section title="Patient overview" eyebrow="AT A GLANCE"><FactGrid items={[["Patient",p.name],["Patient ID",p.id],["Age",p.age],["Gender",p.gender],["Language",summary?.patient_overview?.language||structured.language],["Care type",careType==='ayush'?'AYUSH / Ayurveda':'General Doctor / Allopathy'],["Department",e.department],["Encounter ID",e.id],["Encounter date",formatDate(e.visit_date)],["Token",`A-${String(e.token_number).padStart(3,'0')}`]]}/></Section>

   <Section title="30-second clinical brief" eyebrow="PATIENT HANDOFF">
    <div className="doctor-brief-head"><div><span className="brief-badge">PATIENT-REPORTED</span><span className="brief-badge brief-badge-ai">AI-STRUCTURED</span><p className="brief-helper">Rapid orientation only. AI-structured content is not a diagnosis or clinician confirmation.</p><div className="brief-meta"><span><strong>Priority</strong> {e.priority?String(e.priority).replaceAll('_',' '):'Not assigned'}</span><span><strong>Documents</strong> {Number(brief.documents?.count ?? docs.length) || 0} available</span></div></div><button className="btn btn-outline" onClick={readSummary} disabled={!summary||speaking}>{speaking?'Speaking…':'🔊 Read brief'}</button></div>
    <div className="clinical-brief">
      <BriefSection title="Presenting concern" provenance="Patient-reported"><div className="brief-primary-value">{textValue(brief.presenting_concern?.value||summary?.chief_complaint||e.reason)}</div></BriefSection>
      <BriefSection title="Duration / history" provenance="Patient-reported"><ListBlock items={briefItems(brief.history)}/></BriefSection>
      <BriefSection title="Associated symptoms" provenance="Patient-reported"><ListBlock items={briefItems(brief.reported_symptoms)}/></BriefSection>
      <BriefSection title="Safety" provenance="AI-structured" className={`brief-safety ${safety.status==='review_required'?'has-alert':''}`}>
        <div className="brief-safety-state"><span aria-hidden="true">{safety.status==='review_required'?'⚠':safety.status==='no_alert_identified'?'✓':'•'}</span><strong>{safety.label||'Not available'}</strong></div>
        <p>{safety.message||'Safety information was not available in the intake data.'}</p>
        {flags.length>0&&<ul className="summary-bullet-list">{flags.slice(0,4).map((f,index)=><li key={f.id||f.label||index}>{f.label||'Safety signal'}{f.evidence?.length?` — ${f.evidence.join(', ')}`:''}</li>)}</ul>}
      </BriefSection>
      <BriefSection title="Important background" provenance="Patient-reported"><ListBlock items={briefItems(brief.important_background)}/></BriefSection>
      <BriefSection title="Verify before decision" provenance="AI-structured review prompts"><ListBlock items={briefItems(brief.verify)} empty="Not available"/></BriefSection>
      <div className="brief-footer"><span>Patient-reported = source intake</span><span>AI-structured = organized from persisted data</span><span>Clinician-verified = only doctor-entered information</span><span>Documents: {Number(brief.documents?.count ?? docs.length) || 0} available</span></div>
    </div>
    {voiceMessage&&<div className="voice-note">{voiceMessage}</div>}
   </Section>

   <Section title="Chief complaint" eyebrow="PRESENTING PROBLEM"><div className="clinical-highlight"><strong>{summary?.chief_complaint||e.reason||'Not available'}</strong></div></Section>

   <Section title="Key symptoms" eyebrow="WHAT THE PATIENT REPORTED"><ListBlock items={(summary?.key_symptoms||[]).map(x=>typeof x==='object'?`${x.field}: ${x.value}`:x)}/></Section>

   <Section title="History of present illness" eyebrow="STRUCTURED HISTORY"><ListBlock items={summary?.history_of_present_illness||summary?.history_points}/></Section>

   <Section title="Important findings" eyebrow="PATIENT EVIDENCE"><div className="two-column-summary"><div><h3>Positive findings</h3><ListBlock items={summary?.important_positive_findings}/></div><div><h3>Meaningful negatives</h3><ListBlock items={summary?.important_negative_findings}/></div></div></Section>

   <Section title="Red flags & safety" eyebrow="CLINICAL SAFETY"><div className={`safety-card ${safetyLevelValue}`}><div className="safety-header"><div className="safety-title-wrap"><span className="safety-status-icon" aria-hidden="true">{safetyLevelValue==='emergency'?'🚨':safetyLevelValue==='urgent'?'⚠️':safetyStatus==='complete'?'✓':'•'}</span><div><strong>{safetyTitle(flags,severity,safetyStatus)}</strong><span className="safety-severity">Severity: {String(severity).replaceAll('_',' ').toUpperCase()}</span></div></div><Pill value={flags.length?String(flags[0]?.level||safetyLevelValue):safetyStatus}/></div>{flags.length?<div className="safety-alert-list">{flags.map((f,i)=><article key={f.id||f.label||i}><div className="safety-alert-title"><span aria-hidden="true">{String(f.level||'').toLowerCase()==='emergency'?'🚨':'⚠️'}</span><strong>{f.label||'Safety signal'}</strong></div><p>{f.message||f.rationale||'Patient-reported safety signal requiring clinician review.'}</p>{f.evidence?.length&&<small>Patient evidence: {f.evidence.join(', ')}</small>}</article>)}</div>:<div className="safety-clear"><strong>{safetyStatus==='complete'?'No safety concern identified from the available responses.':'Safety assessment incomplete.'}</strong><p>{safetyStatus==='complete'?'Continue routine clinician review and verify the patient history.':'Complete the clinical review before considering the encounter ready.'}</p></div>}<div className="safety-action"><strong>Doctor action</strong><span>{flags.length?'Review the highlighted signals and verify the supporting patient evidence.':safetyStatus==='complete'?'Continue with routine clinical review.':'Review the available history before proceeding.'}</span></div><p className="muted">Safety signals support triage only; they are not diagnoses.</p></div></Section>

   <Section title="Medical history" eyebrow="BACKGROUND"><FactGrid items={[["Past history",summary?.medical_history?.['Past history']||structured.past_history],["Family history",summary?.medical_history?.['Family history']||structured.family_history],["Personal history",summary?.medical_history?.['Personal history']||structured.personal_history],["Medications",summary?.medications||structured.medications],["Allergies",summary?.allergies||structured.allergies]]}/></Section>

   {<Section title="AYUSH / Dashavidha Pariksha" eyebrow="OPTIONAL ASSESSMENT">{ayush?<><p className="summary-copy">{ayush.summary||'AYUSH assessment completed.'}</p>{w.ayush_consultation?.ai_summary?.clinical_summary&&<div className="ai-summary-box"><strong>AYUSH health summary</strong><p>{w.ayush_consultation.ai_summary.clinical_summary}</p></div>}<div className="answer-evidence-grid">{Object.entries(ayush.responses||{}).filter(([k,v])=>!k.startsWith('__')&&v!==''&&v!=null).map(([k,v])=><div key={k}><span>{k.replaceAll('_',' ')}</span><strong>{textValue(v)}</strong></div>)}</div></>:<p className="muted">AYUSH assessment not completed.</p>}</Section>}

   <Section title="Documents" eyebrow={`${docs.length} ON RECORD`}>{docs.length?<div className="doc-list">{docs.map(d=><article className="doc-row" key={d.id}><span className="doc-icon">📄</span><div><strong>{d.filename}</strong><small>{d.document_type} · {formatDate(d.created_at)} · Encounter {d.encounter_id||'not linked'}</small></div><Pill value={d.verification_status||d.status}/></article>)}</div>:<p className="muted">No documents are available.</p>}</Section>

   <Section title="Interview Q&A" eyebrow="COMPLETE PATIENT EVIDENCE"><details className="qa-disclosure" open><summary>View all questions and answers ({(w.interview||[]).length})</summary><div className="interview-evidence-list">{(w.interview||[]).map((item,index)=><article className="interview-evidence-row" key={`${item.question_id||index}-${index}`}><div><strong>{index+1}. {item.question}</strong><p>{item.skipped?'Skipped':item.answer||'No answer recorded'}</p></div><Pill value={item.skipped?'Skipped':item.input_mode||'text'}/></article>)}{!(w.interview||[]).length&&<p className="muted">No interview evidence recorded.</p>}</div></details></Section>

   <Section title={record?'Consultation notes':'Start consultation'} eyebrow="PHYSICIAN REVIEW">{!record?<><p className="muted">Call the patient before starting the consultation record.</p><button className="btn btn-primary btn-xl" onClick={start} disabled={busy||!['called','in_consultation'].includes(e.status)}>{busy?'Starting…':'Start consultation'}</button></>:<div className="review-form">{Object.keys(EMPTY).map(k=><div className="consultation-section-field" key={k}><label className="field"><span>{labels[k]}</span><textarea rows="3" value={sections[k]||''} onChange={ev=>setSections({...sections,[k]:ev.target.value})}/></label></div>)}<label className="field"><span>Doctor notes</span><textarea rows="4" value={notes} onChange={ev=>setNotes(ev.target.value)}/></label><label className="field"><span>Review status</span><select value={review} onChange={ev=>setReview(ev.target.value)}><option>Pending</option><option>Reviewed</option><option>Needs Follow-up</option><option>Urgent Review</option><option>Completed</option></select></label><div className="consultation-quick-actions"><button type="button" className="btn btn-light" onClick={()=>setReviewStatus('Needs Follow-up')} disabled={saving}>Needs follow-up</button><button type="button" className="btn btn-light" onClick={()=>setReviewStatus('Urgent Review')} disabled={saving}>Requires urgent review</button></div><div className="bottom-action"><button className="btn btn-primary btn-xl" onClick={save} disabled={saving}>{saving?'Saving…':'Save notes'}</button><button className="btn btn-outline btn-xl" onClick={complete} disabled={saving||e.status==='completed'}>Complete consultation</button></div></div>}</Section>
  </main>
  <aside className="clinical-side"><div className="sticky"><Section title="Queue" eyebrow="PATIENT FLOW"><p className="muted">Token A-{String(e.token_number).padStart(3,'0')} · {String(e.status||'unknown').replaceAll('_',' ')}</p><button className="btn btn-primary full" onClick={call} disabled={busy||e.status!=='waiting'}>{busy?'Calling…':'Call patient'}</button></Section><Section title="Clinical priority"><div className="priority-large">{priorityLabel(e.priority)}</div><p className="muted">Queue priority is operational. Clinical safety is shown separately.</p></Section><Section title="Clinical gate"><p className="muted">{gate?.ready_for_routine_consultation?gate.clinician_action:gate?.clinician_action||'Review the consultation and safety information before completion.'}</p></Section></div></aside>
  </div></div>;
}
