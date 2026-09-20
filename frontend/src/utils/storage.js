const JOURNEY_PREFIX = 'aarogyasaar.journey.v2';

export function journeyKey(userId) { return `${JOURNEY_PREFIX}.${userId}`; }
export function loadJourney(userId) {
  try { return JSON.parse(sessionStorage.getItem(journeyKey(userId)) || '{}'); } catch { return {}; }
}
export function saveJourney(userId, patch) {
  const next = { ...loadJourney(userId), ...patch, userId };
  sessionStorage.setItem(journeyKey(userId), JSON.stringify(next));
  return next;
}
export function clearJourney(userId) { if (userId) sessionStorage.removeItem(journeyKey(userId)); }
