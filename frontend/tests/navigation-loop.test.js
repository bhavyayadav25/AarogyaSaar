import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const root = new URL('../src/', import.meta.url);
const read = name => fs.readFileSync(new URL(name, root), 'utf8');

test('completed interview follows the single optional AYUSH transition', () => {
  const interview = read('pages/patient/Interview.jsx');
  assert.match(interview, /r\.completed.*ayush-transition/s);
  assert.doesNotMatch(interview, /r\.completed.*nav\('\/patient\/documents'/s);
});

test('patient navigation guard does not bounce completed interviews between visit and documents', () => {
  const layout = read('layouts/PatientLayout.jsx');
  const visit = read('pages/patient/Visit.jsx');
  assert.match(layout, /j\.interviewComplete && \(j\.ayushComplete \|\| j\.ayushSkipped\)/);
  assert.match(visit, /hydrated\.interviewComplete && !hydrated\.ayushComplete && !hydrated\.ayushSkipped/);
});

test('user-facing frontend contains no internal phase labels', () => {
  const files = ['pages/Landing.jsx','pages/patient/Visit.jsx','pages/patient/Interview.jsx','pages/patient/AyushTransition.jsx','pages/patient/Ayush.jsx','pages/patient/Documents.jsx','pages/patient/Completion.jsx','pages/doctor/Encounter.jsx','pages/admin/Dashboard.jsx'];
  const all = files.map(read).join('\n');
  for (const token of ['AI-5F','Phase 5C','Phase 5B','Phase 4E','Phase 4F','AI/NLP','AI Analysis']) assert.equal(all.includes(token), false, `internal label remains: ${token}`);
});

test('fresh patient visit ignores stale client journey when backend reports no active encounter', () => {
  const visit = read('pages/patient/Visit.jsx');
  assert.match(visit, /const resumable=!!activeEncounter/);
  assert.match(visit, /const j=resumable \? storedJourney : \{\}/);
  assert.match(visit, /if\(!resumable && Object\.keys\(storedJourney\)\.length\)/);
  assert.match(visit, /clearJourney\(id\)/);
  assert.match(visit, /language:j\.language\|\|''/);
});

test('patient language selection is explicit and limited to the existing language source', () => {
  const visit = read('pages/patient/Visit.jsx');
  const constants = read('utils/constants.js');
  assert.match(visit, /Object\.entries\(LANGUAGES\)/);
  assert.match(visit, /saveJourney\(id,\{language\}\)/);
  assert.match(constants, /en-IN/);
  assert.match(constants, /hi-IN/);
  assert.match(constants, /bn-IN/);
});

test('backend active encounter contract only resumes genuinely active queue states', () => {
  const backend = fs.readFileSync(new URL('../../backend/main.py', import.meta.url), 'utf8');
  assert.match(backend, /Encounter\.status\.in_\(\["waiting", "called", "in_consultation"\]\)/);
  assert.doesNotMatch(backend, /active-encounter[\\s\\S]{0,1000}status\.in_\(\[[^\]]*completed/);
});
