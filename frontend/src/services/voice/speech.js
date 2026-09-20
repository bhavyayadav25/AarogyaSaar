import { api } from '../../api/client';

let generation = 0;
let activeAudio = null;
let activeUrl = null;

export function stopSpeech() {
  generation += 1;
  if (activeAudio) {
    try { activeAudio.pause(); activeAudio.currentTime = 0; } catch { /* no-op */ }
    activeAudio.onended = null; activeAudio.onerror = null; activeAudio = null;
  }
  if (activeUrl) { URL.revokeObjectURL(activeUrl); activeUrl = null; }
  if (typeof window !== 'undefined' && window.speechSynthesis) {
    try { window.speechSynthesis.cancel(); } catch { /* no-op */ }
  }
}

function pickVoice(language) {
  const voices = window.speechSynthesis?.getVoices?.() || [];
  const prefix = language.split('-')[0].toLowerCase();
  const compatible = voices.filter((v) => (v.lang || '').toLowerCase().startsWith(prefix));
  if (!compatible.length) return null;
  const femaleHints = ['female', 'zira', 'sara', 'swara', 'neerja', 'tanishaa', 'priya'];
  return compatible.find((v) => femaleHints.some((h) => v.name.toLowerCase().includes(h))) || compatible[0];
}

export function browserSpeak(text, language, speed = 1) {
  return new Promise((resolve, reject) => {
    if (!window.speechSynthesis || !text) return reject(new Error('Voice playback is unavailable.'));
    const myGeneration = generation;
    try { window.speechSynthesis.cancel(); } catch { /* no-op */ }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = language;
    utterance.rate = Number(speed) || 1;
    const voice = pickVoice(language);
    if (voice) utterance.voice = voice;
    utterance.onend = () => myGeneration === generation ? resolve() : resolve();
    utterance.onerror = () => myGeneration === generation ? reject(new Error('Voice playback is unavailable.')) : resolve();
    window.speechSynthesis.speak(utterance);
  });
}

export async function speakText(token, text, language, speed = 1) {
  if (!text) return;
  stopSpeech();
  const myGeneration = generation;
  try {
    const blob = await api.speak(token, text, language);
    if (myGeneration !== generation) return;
    if (!(blob instanceof Blob) || !blob.size) throw new Error('No audio was returned.');
    activeUrl = URL.createObjectURL(blob);
    const audio = new Audio(activeUrl);
    activeAudio = audio;
    audio.playbackRate = Number(speed) || 1;
    await new Promise((resolve, reject) => {
      audio.onended = resolve;
      audio.onerror = () => reject(new Error('Voice playback is unavailable.'));
      audio.play().catch(reject);
    });
  } catch (error) {
    if (myGeneration !== generation) return;
    await browserSpeak(text, language, speed);
  } finally {
    if (myGeneration === generation) stopSpeech();
  }
}

export const speakQuestion = speakText;
