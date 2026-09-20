import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const pages=[];function walk(d){for(const n of fs.readdirSync(d)){const p=path.join(d,n);const s=fs.statSync(p);if(s.isDirectory())walk(p);else if(p.endsWith('.jsx'))pages.push(p)}}walk('src');
test('fresh frontend has patient and doctor page areas',()=>{assert.ok(pages.some(p=>p.includes('pages/patient')));assert.ok(pages.some(p=>p.includes('pages/doctor')));});
test('global error boundary exists',()=>assert.ok(fs.existsSync('src/components/GlobalErrorBoundary.jsx')));
test('voice service exists',()=>assert.ok(fs.existsSync('src/services/voice/speech.js')));
test('patient language contract is exactly English, Hindi and Bangla',()=>{
  const constants=fs.readFileSync('src/utils/constants.js','utf8');
  assert.ok(constants.includes("'en-IN': 'English'"));
  assert.ok(constants.includes("'hi-IN': 'हिन्दी'"));
  assert.ok(constants.includes("'bn-IN': 'বাংলা'"));
  for (const code of ['ta-IN','te-IN','mr-IN','gu-IN','kn-IN','ml-IN','pa-IN']) assert.equal(constants.includes(code),false,`unsupported language ${code} remains`);
});
test('patient UI contains no internal development phase labels',()=>{
  let all=''; for(const p of pages) all+=fs.readFileSync(p,'utf8')+'\n';
  for(const token of ['AI-1','AI-2','AI-3','AI-4B','AI-5H','PHASE 5A','PHASE 5B','FIX2DOC','fix2doc.txt','MOCK','PLACEHOLDER','SEEDED IN BACKEND']) assert.equal(all.includes(token),false,`internal label ${token} remains in patient/role UI`);
});

test('final patient onboarding keeps one language set and removes patient department selection', () => {
  const visit = fs.readFileSync('src/pages/patient/Visit.jsx','utf8');
  const layout = fs.readFileSync('src/layouts/PatientLayout.jsx','utf8');
  assert.ok(!visit.includes("stage==='aadhaar'"));
  assert.ok(!visit.includes("stage==='department'"));
  assert.ok(!layout.includes("'aadhaar'"));
  assert.ok(!layout.includes("STEP_KEYS = ['language','department'"));
  assert.equal((visit.match(/'en-IN'/g) || []).length > 0, true);
});

test('landing page contains the single Ministry of Ayush logo and patient pages do not render it', () => {
  const landing = fs.readFileSync('src/pages/Landing.jsx','utf8');
  const ayush = fs.readFileSync('src/pages/patient/Ayush.jsx','utf8');
  const transition = fs.readFileSync('src/pages/patient/AyushTransition.jsx','utf8');
  assert.equal((landing.match(/Logo_Ministry_of_AYUSH\.png/g) || []).length, 1);
  assert.ok(landing.includes('landing-ayush-mark'));
  assert.equal(ayush.includes('Logo_Ministry_of_AYUSH.png'), false);
  assert.equal(transition.includes('Logo_Ministry_of_AYUSH.png'), false);
});

test('doctor workspace renders structured handoff and safety sections', () => {
  const encounter = fs.readFileSync('src/pages/doctor/Encounter.jsx','utf8');
  assert.ok(encounter.includes('30-second clinical brief'));
  assert.ok(encounter.includes('Red flags & safety'));
  assert.ok(encounter.includes('Interview Q&A'));
  assert.ok(encounter.includes('AYUSH / Dashavidha Pariksha'));
});

test('doctor review contains no voice-input microphone while patient voice input remains', () => {
  const encounter = fs.readFileSync('src/pages/doctor/Encounter.jsx','utf8');
  const voiceInput = fs.readFileSync('src/components/VoiceInput.jsx','utf8');
  assert.equal(encounter.includes('VoiceInput'), false);
  assert.ok(voiceInput.includes('startRecognition'));
  assert.ok(voiceInput.includes('hi-IN'));
  assert.ok(voiceInput.includes('bn-IN'));
});

test('doctor encounter does not reference an undefined AYUSH workspace variable', () => {
  const encounter = fs.readFileSync('src/pages/doctor/Encounter.jsx','utf8');
  assert.equal(encounter.includes('ws.ayush_consultation'), false);
  assert.ok(encounter.includes('w.ayush_consultation'));
});
test('doctor encounter exposes persistent identity and consultation review controls', () => {
  const encounter = fs.readFileSync('src/pages/doctor/Encounter.jsx','utf8');
  assert.ok(encounter.includes('["Patient ID",p.id]'));
  assert.ok(encounter.includes('["Encounter ID",e.id]'));
  assert.ok(encounter.includes('Needs Follow-up'));
  assert.ok(encounter.includes('Urgent Review'));
  assert.ok(encounter.includes('api.reviewConsultation'));
});

test('patient home imports the journey loader it uses and guards the empty journey state', () => {
  const home = fs.readFileSync('src/pages/patient/Home.jsx','utf8');
  assert.ok(home.includes("import { loadJourney } from '../../utils/storage';"));
  assert.ok(home.includes('const journey=loadJourney(id);'));
});

test('patient home keeps primary accessibility controls localized', () => {
  const home = fs.readFileSync('src/pages/patient/Home.jsx','utf8');
  assert.ok(home.includes("accessibility:'Accessibility'"));
  assert.ok(home.includes("accessibility:'सुगमता'"));
  assert.ok(home.includes("accessibility:'সহজ ব্যবহার'"));
});

test('doctor dashboard provides judge-friendly queue metrics and filters', () => {
  const dashboard = fs.readFileSync('src/pages/doctor/Dashboard.jsx','utf8');
  assert.ok(dashboard.includes('Total assigned'));
  assert.ok(dashboard.includes('Priority review'));
  assert.ok(dashboard.includes('Patient queue'));
  assert.ok(dashboard.includes('role="tablist"'));
  assert.ok(dashboard.includes('Open encounter →'));
  assert.ok(dashboard.includes('queueMeta'));
});

test('doctor consultation flow keeps handoff separate from clinician record', () => {
  const encounter = fs.readFileSync('src/pages/doctor/Encounter.jsx','utf8');
  assert.ok(encounter.includes("c.consultation_type==='clinician' || c.title==='Clinical consultation'"));
  assert.ok(encounter.includes('await api.startConsultation'));
  assert.ok(encounter.includes('await load()'));
  assert.ok(encounter.includes('Interview Q&A'));
  assert.ok(encounter.includes('Red flags & safety'));
  assert.ok(encounter.includes('Documents'));
});

test('doctor 30-second brief is structured and provenance-aware', () => {
  const encounter = fs.readFileSync('src/pages/doctor/Encounter.jsx','utf8');
  assert.ok(encounter.includes('30-second clinical brief'));
  for (const section of ['Presenting concern','Duration / history','Associated symptoms','Safety','Important background','Verify before decision']) assert.ok(encounter.includes(section));
  assert.ok(encounter.includes('PATIENT-REPORTED'));
  assert.ok(encounter.includes('AI-STRUCTURED'));
  assert.ok(encounter.includes('brief_sections'));
  assert.ok(encounter.includes('summarySource=general'));
  assert.ok(!encounter.includes('const summarySource=general||clinical'));
  assert.ok(encounter.includes('Documents:'));
});

test('step 6 accessibility and responsive polish contracts remain present', () => {
  const css = fs.readFileSync('src/styles/app.css','utf8');
  const voice = fs.readFileSync('src/components/VoiceInput.jsx','utf8');
  const home = fs.readFileSync('src/pages/patient/Home.jsx','utf8');
  assert.ok(css.includes('@media(max-width:768px)'));
  assert.ok(css.includes('@media(max-width:560px)'));
  assert.ok(css.includes('@media(prefers-reduced-motion:reduce)'));
  assert.ok(css.includes('.high-contrast'));
  assert.ok(css.includes('min-height:46px'));
  assert.ok(voice.includes("aria-pressed={state==='recording'}"));
  assert.ok(home.includes('aria-pressed={preferences.audio_enabled}'));
  assert.ok(home.includes('aria-pressed={preferences.high_contrast}'));
});

test('shared error state hides technical transport details from users', () => {
  const states = fs.readFileSync('src/components/States.jsx','utf8');
  assert.ok(states.includes('safeMessage'));
  assert.ok(states.includes('status code'));
  assert.ok(states.includes('Something went wrong while loading your information. Please try again.'));
});

test('patient Home localizes common backend-derived values without changing stored data', () => {
  const home = fs.readFileSync('src/pages/patient/Home.jsx','utf8');
  const text = fs.readFileSync('src/utils/patientText.js','utf8');
  assert.ok(home.includes('patientDepartmentLabel(active.department||\'—\',preferences.language)'));
  assert.ok(home.includes('patientValueLabel(profile?.gender,preferences.language)'));
  assert.ok(home.includes('patientValueLabel(active.status,preferences.language)'));
  assert.ok(text.includes("Female:'महिला'"));
  assert.ok(text.includes("waiting:'प्रतीक्षा में'"));
  assert.ok(text.includes("Female:'মহিলা'"));
  assert.ok(text.includes("waiting:'অপেক্ষায়'"));
});

test('patient documents and AYUSH controls remain localized for Hindi and Bangla', () => {
  const docs = fs.readFileSync('src/pages/patient/Documents.jsx','utf8');
  const ayush = fs.readFileSync('src/pages/patient/Ayush.jsx','utf8');
  assert.ok(docs.includes("Prescription: 'दवाइयों की पर्ची'"));
  assert.ok(docs.includes("Prescription: 'ওষুধের প্রেসক্রিপশন'"));
  assert.ok(docs.includes('actions.open'));
  assert.ok(ayush.includes("preferences.language==='hi-IN'?'आयुष देखभाल'"));
  assert.ok(ayush.includes("preferences.language==='bn-IN'?'আয়ুষ সেবা'"));
});


test('patient interview paths do not render answer voice-input controls', () => {
  for (const file of ['Interview.jsx', 'Ayush.jsx', 'Visit.jsx']) {
    const source = fs.readFileSync(`src/pages/patient/${file}`, 'utf8');
    assert.equal(source.includes('VoiceInput'), false, `${file} still exposes patient answer voice input`);
  }
  const interview = fs.readFileSync('src/pages/patient/Interview.jsx', 'utf8');
  const ayush = fs.readFileSync('src/pages/patient/Ayush.jsx', 'utf8');
  assert.equal(interview.includes('Speak Answer'), false);
  assert.equal(ayush.includes('Speak Answer'), false);
});
