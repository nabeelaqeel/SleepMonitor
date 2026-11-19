// Merging the persisted alert history (GET /alerts) into the live eventLog —
// pure functions so the dedupe stays unit-checkable outside React Native.
// GET /alerts ts is ISO-8601 UTC; live rows display the payload's UTC
// 'HH:MM AM/PM' stamp — history rows are formatted the same way so both
// sources read alike.
export function alertTimeLabel(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const h24 = d.getUTCHours();
  const h = String(h24 % 12 || 12).padStart(2, '0');
  return `${h}:${String(d.getUTCMinutes()).padStart(2, '0')} ${h24 >= 12 ? 'PM' : 'AM'}`;
}

// Live and persisted copies of the same alert dedupe on
// (severity, publish second, spo2, hr) — patient-independent, because the
// doctor's log spans patients. Live rows carry the publish epoch (tsMs, what
// the DB stores as readings.published_at); history rows get theirs from the
// endpoint's ts. Live entries win: they are fresher.
const secondBucket = ms => Math.floor(ms / 1000);

export function dedupeKey({ tier, tsMs, spo2, hr }) {
  return `${tier}|${Number.isFinite(tsMs) ? secondBucket(tsMs) : ''}|${spo2}|${hr}`;
}

// Newest first across both sources; a live row without a publish stamp
// counts as freshest (it was just received).
export const msOf = e => (Number.isFinite(e.tsMs) ? e.tsMs : Date.now());

/** Maps one GET /alerts row into an EventLog-compatible entry. */
export function mapHistoryRow(row, roster) {
  return {
    id:       `hist-${row.alert_id}`,
    tier:     row.severity,
    time:     alertTimeLabel(row.ts),
    spo2:     row.spo2 ?? '—',
    hr:       row.heart_rate ?? '—',
    duration: '—',
    // severity ↔ topic is a fixed pipeline mapping (sleep/<tier key>).
    topic:    row.severity === 'Critical' ? 'sleep/critical' : 'sleep/important',
    // No alert reason in the history payload — the caption line carries the
    // patient name instead (payload value, roster-join fallback).
    reason:   row.patient_name
              || roster.find(p => p.id === row.patient_id)?.name
              || '—',
    tsMs:     Date.parse(row.ts),
  };
}

/** Live eventLog + history rows → one newest-first list; live entries win on
 *  a dedupe collision. A null/failed history keeps the live log untouched. */
export function mergeAlerts(eventLog, history, roster) {
  if (!history) return eventLog;
  const liveKeys = new Set(eventLog.map(dedupeKey));
  const historyEntries = history
    .filter(row => !liveKeys.has(dedupeKey({
      tier: row.severity,
      tsMs: Date.parse(row.ts),
      spo2: row.spo2,
      hr:   row.heart_rate,
    })))
    .map(row => mapHistoryRow(row, roster));
  return [...eventLog, ...historyEntries].sort((a, b) => msOf(b) - msOf(a));
}

