// Patient speech-to-text controller.
// The browser recognizer is kept isolated to one active session.  Every
// recognised segment is delivered immediately so the patient's textarea is
// updated while they speak; normal browser onend events are treated as a
// pause, not as completion.  The caller explicitly stops the session.
let recognition = null;
let active = false;
let manuallyStopped = false;
let fatalError = '';
let language = 'en-IN';
let listener = null;
let restartTimer = null;
let sessionId = 0;
let finalTranscript = '';
let interimTranscript = '';
let lastTranscript = '';
let finalSegments = [];
let seenFinalResults = new Set();

function RecognitionCtor() {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function emit(state, extra = {}) {
  listener?.({ state, language, transcript: lastTranscript, ...extra });
}

function clearRestart() {
  if (restartTimer) {
    clearTimeout(restartTimer);
    restartTimer = null;
  }
}

function normalise(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function configure(mySession) {
  const Ctor = RecognitionCtor();
  if (!Ctor) return null;
  // A fresh recognition object per user session prevents late onend/onerror
  // events from an old session from changing the current patient's answer.
  recognition = new Ctor();
  const r = recognition;

  r.continuous = true;
  r.interimResults = true;
  r.maxAlternatives = 1;
  r.lang = language;

  r.onstart = () => {
    if (mySession !== sessionId) return;
    active = true;
    emit('listening');
  };

  r.onresult = (event) => {
    if (mySession !== sessionId) return;

    const finalParts = [];
    const interimParts = [];
    // event.results contains the recognizer's current transcript window.  Use
    // every result so Chrome's resultIndex updates cannot drop earlier words.
    for (let i = 0; i < event.results.length; i += 1) {
      const result = event.results[i];
      const text = normalise(result?.[0]?.transcript);
      if (!text) continue;
      if (result.isFinal) finalParts.push(text);
      else interimParts.push(text);
    }

    // Keep final segments across Chrome result-window updates. Some browsers
    // expose only the changed portion of event.results, so rebuilding solely
    // from the current event can make earlier words disappear.
    for (let i = 0; i < event.results.length; i += 1) {
      const result = event.results[i];
      if (!result?.isFinal) continue;
      const text = normalise(result?.[0]?.transcript);
      if (!text) continue;
      const key = `${(event.resultIndex ?? 0) + i}|${text}`;
      if (!seenFinalResults.has(key)) {
        seenFinalResults.add(key);
        finalSegments.push(text);
      }
    }
    finalTranscript = normalise(finalSegments.join(' '));
    interimTranscript = normalise(interimParts.join(' '));
    lastTranscript = normalise([finalTranscript, interimTranscript].filter(Boolean).join(' '));

    if (lastTranscript) {
      emit('result', {
        text: lastTranscript,
        isFinal: Boolean(finalTranscript && !interimTranscript),
      });
    }
  };

  r.onnomatch = () => {
    if (mySession === sessionId) emit('nomatch');
  };

  r.onerror = (event) => {
    if (mySession !== sessionId) return;
    const error = event?.error || 'unknown';

    if (error === 'aborted' && manuallyStopped) return;

    if (error === 'not-allowed' || error === 'service-not-allowed') {
      fatalError = 'permission';
      active = false;
      manuallyStopped = true;
      clearRestart();
      emit('error', { error: 'permission' });
      return;
    }

    if (error === 'audio-capture') {
      fatalError = 'microphone';
      active = false;
      manuallyStopped = true;
      clearRestart();
      emit('error', { error: 'microphone' });
      return;
    }

    // Chrome can report a network error for its cloud speech service even
    // though microphone capture is working.  VoiceInput uses this signal to
    // switch to the local/server Whisper recorder fallback.
    if (error === 'network') {
      fatalError = 'network';
      active = false;
      manuallyStopped = true;
      clearRestart();
      emit('error', { error: 'network', recoverable: true });
      return;
    }

    active = false;
    manuallyStopped = true;
    clearRestart();
    emit('error', { error, recoverable: false });
  };

  r.onend = () => {
    if (mySession !== sessionId) return;
    active = false;

    if (manuallyStopped && !fatalError) {
      // Some Chromium builds deliver the final result asynchronously after
      // stop(). The session remains valid until onend so that result is not
      // discarded by a premature sessionId/listener reset.
      if (lastTranscript) emit('result', { text: lastTranscript, isFinal: true });
      emit('stopped');
      clearRestart();
      recognition = null;
      listener = null;
      return;
    }

    // A normal onend is commonly caused by a short pause. Preserve the final
    // words and restart the same session instead of making the patient tap mic
    // repeatedly.
    emit('restarting');
    clearRestart();
    restartTimer = setTimeout(() => {
      if (mySession !== sessionId || manuallyStopped || fatalError || !recognition) return;
      try {
        recognition.start();
      } catch {
        // An already-running recognizer will continue through its own events.
      }
    }, 200);
  };

  return r;
}

export function isRecognitionSupported() {
  return !!RecognitionCtor();
}

export function startRecognition(nextLanguage, onEvent) {
  stopRecognition();

  const Ctor = RecognitionCtor();
  if (!Ctor) {
    onEvent?.({ state: 'unsupported', language: nextLanguage || 'en-IN' });
    return false;
  }

  sessionId += 1;
  const mySession = sessionId;
  listener = onEvent || null;
  language = ['en-IN', 'hi-IN', 'bn-IN'].includes(nextLanguage) ? nextLanguage : 'en-IN';
  finalTranscript = '';
  interimTranscript = '';
  finalSegments = [];
  seenFinalResults = new Set();
  lastTranscript = '';
  fatalError = '';
  manuallyStopped = false;
  clearRestart();

  const r = configure(mySession);
  try {
    r.start();
    return true;
  } catch (error) {
    active = false;
    emit('error', { error: 'start-failed', detail: error, recoverable: true });
    return false;
  }
}

export function stopRecognition() {
  manuallyStopped = true;
  clearRestart();
  active = false;

  const r = recognition;
  if (!r) {
    listener = null;
    return;
  }

  // IMPORTANT: do not invalidate sessionId or clear listener here. The browser
  // is allowed to emit a final onresult after stop() and before onend. Keeping
  // the session alive through onend guarantees that final transcript reaches
  // the caller and therefore the controlled patient answer input.
  try {
    r.stop();
  } catch {
    try { r.abort(); } catch { /* no-op */ }
  }
}

export function recognitionIsActive() {
  return active;
}
