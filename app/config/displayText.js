// ─────────────────────────────────────────────────────────────────────────────
// displayText.js — every string the app SHOWS to a user, in one place.
//
// HOW TO USE THIS FILE:
//   • Edit ONLY the values on the right side of the colons (the quoted text).
//   • NEVER rename the keys on the left (healthy, monitor, Critical, footer,
//     …). Those are internal code identifiers — payload fields, MQTT tier
//     names, storage keys — and the app's logic depends on them staying
//     exactly as they are.
//   • Changing text here only changes what the user sees. It never alters the
//     MQTT topics (sleep/critical, sleep/important, …), the classifier, or
//     the AI module, which are intentionally separate.
// ─────────────────────────────────────────────────────────────────────────────

// ── AI sleep-assessment bands ────────────────────────────────────────────────
// Keys ("band" values) come from the trained model payload on
// sleep/recommendation — do not rename. Values are the user-facing tier names.
export const AI_BAND_LABELS = {
  healthy:    'No concerning sleep pattern detected',
  monitor:    'Possible sleep pattern to monitor',
  see_doctor: 'Concerning sleep pattern — consult a clinician',
};

// ── Live severity tiers ──────────────────────────────────────────────────────
// Keys match the tier names in the MQTT payloads and code logic
// (Critical / Important / Normal / Background) — do not rename.
//   LONG  → banner status cards (Home screen, patient detail).
//   SHORT → event badges, filter pills, counts, report legends.
export const TIER_LONG_LABELS = {
  Critical:   'Critical',
  Important:  'Moderate',
  Normal:     'Low Priority',
  Background: 'Backgroud',
};

export const TIER_SHORT_LABELS = {
  Critical:   'Critical',
  Important:  'Moderate',
  Normal:     'Low Priority',
  Background: 'Backgroud',
};

// Banner used when the patient detail screen has no live session.
export const OFFLINE_TIER_LABEL = 'Offline — no live session';

// ── MQTT topic display names ─────────────────────────────────────────────────
// Keys are the REAL broker topics used by the publisher and app logic — do not
// rename. Values are only what the UI shows on screens. Set a value back to
// its key (e.g. 'sleep/critical': 'sleep/critical') to show the raw topic
// again. This never changes what is actually published or subscribed to.
export const TOPIC_DISPLAY_LABELS = {
  'sleep/critical':   'sleep/urgent',
  'sleep/important':  'sleep/moderate',
  'sleep/normal':     'sleep/low-priority',
  'sleep/background': 'sleep/background',
};

export function topicDisplayLabel(topic) {
  if (typeof topic !== 'string' || topic.length === 0) return '—';
  return Object.hasOwn(TOPIC_DISPLAY_LABELS, topic)
    ? TOPIC_DISPLAY_LABELS[topic]
    : topic;
}

// Per-QoS-level copy on the network screen ("What is each level used for").
// Keys are screen rows (qos2 / qos1 / qos0) — the QoS numbers themselves stay.
export const QOS_LEVEL_TEXT = {
  qos2: {
    useCase: 'Urgent readings — reserved for high-priority alerts',
    explain: 'Exactly-once delivery. The broker stores the message and waits for acknowledgement. Used for the highest-priority readings.',
  },
  qos1: {
    useCase: 'Watch readings — moderate-priority trends',
    explain: 'At least once delivery. Messages may duplicate but are never lost. Used for moderate-priority trends.',
  },
  qos0: {
    useCase: 'Routine readings + background statistics',
    explain: 'Best-effort delivery. May be dropped under network load. Acceptable for routine readings and statistics.',
  },
};

// ── Research-prototype disclaimer furniture ──────────────────────────────────
export const DISCLAIMER = {
  // Always-visible footer at the bottom of result screens.
  footer:
    '⚠️ Research prototype — not a medical device. Guidance only; consult a clinician for medical concerns.',

  // Inline note directly under the sleep-assessment indicator on results.
  inlineNote:
    'This indicator is a proposed sleep-related guidance tier derived from clinical sleep-study data. It is not a diagnosis and has not been validated on your Garmin device.',

  // Shown while no nightly AI recommendation has arrived yet.
  awaiting: 'Awaiting nightly analysis.',

  // Full About / Disclaimer screen. "{{bands}}" is replaced with the
  // AI_BAND_LABELS values (quoted, comma-separated) at render time so the
  // bullet always matches whatever you named the tiers above.
  about: {
    title: 'About this feature',
    intro:
      'This sleep guidance feature is a research prototype and is not a medical device, diagnostic tool, or clinical decision support system.',
    bullets: [
      'The indicators ({{bands}}) are proposed sleep-related guidance tiers, not medical diagnoses.',
      'They are derived from the PAAWS Sleep Protocol dataset (clinical polysomnography), not from your Garmin watch data directly.',
      'Any mapping from sleep-study metrics (e.g., AHI) to these tiers is a research proposal and requires review by a medical professional before clinical use.',
      'Scores shown are model outputs and are not calibrated clinical probabilities unless stated otherwise.',
      'The model has not been validated on wrist-worn Garmin sensors; results may differ from clinical sleep studies.',
    ],
    closing:
      'Do not use this feature for diagnosis, treatment decisions, triage, or any safety-critical purpose. If you have concerns about your sleep or health, consult a qualified healthcare professional.',
  },

  // First-launch acknowledgement screen.
  ackTitle:      'Research prototype',
  ackHint:       'Please read and confirm before continuing.',
  acknowledgement:
    'I understand this feature is a research prototype, is not a medical device or diagnosis, and that I should consult a qualified healthcare professional for any medical concern.',
  agreeLabel: 'I agree',
};

// AsyncStorage key for the first-launch acknowledgement. Changing this key
// silently resets the acknowledgement for every device ("first launch" again).
export const ACK_STORAGE_KEY = 'disclaimer_ack_v1';

// ── Helpers ──────────────────────────────────────────────────────────────────
// One place so a key missing from a map above falls back to the raw code
// identifier instead of crashing a screen.

export function aiBandLabel(band) {
  if (typeof band !== 'string' || band.length === 0) return '—';
  return Object.hasOwn(AI_BAND_LABELS, band) ? AI_BAND_LABELS[band] : band;
}

export function tierLongLabel(tier) {
  if (typeof tier !== 'string' || tier.length === 0) return '—';
  return Object.hasOwn(TIER_LONG_LABELS, tier) ? TIER_LONG_LABELS[tier] : tier;
}

export function tierShortLabel(tier) {
  if (typeof tier !== 'string' || tier.length === 0) return '—';
  return Object.hasOwn(TIER_SHORT_LABELS, tier) ? TIER_SHORT_LABELS[tier] : tier;
}

// "3 urgent · 1 watch" subtitle for the alert screens, built from the short
// labels above so wording changes propagate to both.
export function alertSubtitleCounts(criticalCount, importantCount) {
  return `${criticalCount} ${tierShortLabel('Critical').toLowerCase()} `
       + `· ${importantCount} ${tierShortLabel('Important').toLowerCase()}`;
}

// Expands "{{bands}}" inside DISCLAIMER.about.bullets so wording updates in
// AI_BAND_LABELS above propagate to the About screen automatically.
export function aboutBulletText(bullet) {
  if (typeof bullet !== 'string' || !bullet.includes('{{bands}}')) return bullet;
  return bullet.replaceAll(
    '{{bands}}',
    Object.values(AI_BAND_LABELS).map(label => `"${label}"`).join(', '),
  );
}
