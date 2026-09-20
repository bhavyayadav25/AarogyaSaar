import test from 'node:test';
import assert from 'node:assert/strict';

class FakeRecognition {
  static instances = [];
  constructor(){ this.started=0; this.stopped=0; FakeRecognition.instances.push(this); }
  start(){ this.started++; this.onstart?.(); }
  stop(){ this.stopped++; this.onend?.(); }
  abort(){ this.onend?.(); }
}

global.window = { SpeechRecognition: FakeRecognition, webkitSpeechRecognition: null };
const recognition = await import('../src/services/voice/recognition.js?test=patient-final');

test('patient recognition starts in the selected language and keeps listening after a normal onend', async () => {
  const events=[];
  assert.equal(recognition.startRecognition('hi-IN', e=>events.push(e)), true);
  const first=FakeRecognition.instances.at(-1);
  assert.equal(first.lang,'hi-IN');
  assert.equal(first.continuous,true);
  assert.equal(first.interimResults,true);
  first.onend();
  await new Promise(r=>setTimeout(r,260));
  assert.equal(first.started>=2,true);
  recognition.stopRecognition();
});

test('permission error is surfaced and does not restart', () => {
  const events=[];
  recognition.startRecognition('bn-IN', e=>events.push(e));
  const r=FakeRecognition.instances.at(-1);
  r.onerror?.({error:'not-allowed'});
  assert.equal(events.at(-1).error,'permission');
  const starts=r.started;
  r.onend?.();
  assert.equal(r.started,starts);
  recognition.stopRecognition();
});

test('every speech result is delivered without stopping the microphone', () => {
  const events=[];
  recognition.startRecognition('en-IN', e=>events.push(e));
  const r=FakeRecognition.instances.at(-1);
  const stoppedBeforeResult=r.stopped;
  r.onresult?.({results:[{isFinal:false,0:{transcript:'I have chest'}}]});
  r.onresult?.({results:[{isFinal:true,0:{transcript:'I have chest pain'}}]});
  assert.equal(r.stopped,stoppedBeforeResult);
  assert.equal(events.filter(e=>e.state==='result').at(-1).text,'I have chest pain');
  recognition.stopRecognition();
});

test('final speech result emitted while stopping is not discarded', () => {
  const events=[];
  recognition.startRecognition('hi-IN', e=>events.push(e));
  const r=FakeRecognition.instances.at(-1);
  r.stop = () => {
    r.stopped++;
    r.onresult?.({results:[{isFinal:true,0:{transcript:'आखिरी शब्द'}}]});
    r.onend?.();
  };
  recognition.stopRecognition();
  assert.equal(events.filter(e=>e.state==='result').at(-1).text,'आखिरी शब्द');
});

test('network speech recognition error is explicitly recoverable', () => {
  const events=[];
  recognition.startRecognition('en-IN', e=>events.push(e));
  const r=FakeRecognition.instances.at(-1);
  r.onerror?.({error:'network'});
  assert.equal(events.at(-1).error,'network');
  assert.equal(events.at(-1).recoverable,true);
  recognition.stopRecognition();
});
