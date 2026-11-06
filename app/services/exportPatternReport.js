import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';
import {
  DISCLAIMER,
  aiBandLabel,
  aiBandDescription,
  aboutBulletText,
  patternNextStep,
  PATTERN_REPORT_TEXT,
} from '../config/displayText';

// ── Sleep Pattern Report (nightly PDF export) ────────────────────────────────
// Builds the research-prototype report from the trained-model payload the app
// receives on `sleep/recommendation` (band, p_positive, nightly features +
// per-channel coverage, recording window, model metadata). Anything the
// payload predates renders as "Not available" rather than being invented.
//
// buildPatternReportHtml() is pure (no Expo APIs) so it can be exercised
// without a device; exportPatternReport() renders + shares the PDF.

// Axis bounds used ONLY to place metric bars on a plot. Mirror of the nightly
// plausibility ranges in ai/config.py (hr 30–120 bpm, rmssd 5–200 ms,
// spo2 85–100%) — they never gate or re-classify anything phone-side.
const METRIC_RANGES = {
  hr:    [30, 120],
  rmssd: [5, 200],
  spo2:  [85, 100],
};

// A finding line fires when a nightly feature lands beyond one of these
// research-plausible thresholds (mirrors ai/config.py: desat_threshold_pct 90,
// plus low-side observations for RMSSD). Observation thresholds, not clinical
// cutoffs.
const FINDING_THRESHOLDS = {
  desatFrac:   0.005, // ≥0.5% of readings below 90% SpO2
  spo2Min:     90,    // lowest SpO2 strictly below the desat threshold (exactly 90% does not fire)
  rmssdMedian: 20,    // overnight RMSSD median on the clearly-low side (ms)
};

const BAND_HERO = {
  healthy:    { icon: '✔', color: '#16a34a' },
  monitor:    { icon: '⚠', color: '#d97706' },
  see_doctor: { icon: '❗', color: '#dc2626' },
};

// ── Small pure helpers ────────────────────────────────────────────────────────

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

// Number → clean string with up to `digits` decimals; null when unavailable.
function fmt(value, digits = 1) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return String(Number(value.toFixed(digits)));
}

// Stable short report id derived from the analysed session ("rpt-1a2b3c4d").
function reportIdFrom(payload) {
  const src = typeof payload?.sessionId === 'string' && payload.sessionId
    ? payload.sessionId
    : Math.random().toString(36).slice(2, 10);
  return `rpt-${src.replace(/-/g, '').slice(0, 8)}`;
}

function shortStamp(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const day = d.toLocaleDateString(undefined, { day: '2-digit', month: 'short' });
  const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  return { day, time, ms: d.getTime() };
}

// "23:01 → 05:47 (6h 46m)" — dates included only when the window crosses
// midnight. Returns null when the payload predates the window field.
function windowText(payload) {
  const start = shortStamp(payload?.window?.start);
  const end = shortStamp(payload?.window?.end);
  if (!start || !end) return null;

  let duration = '';
  const mins = Math.round((end.ms - start.ms) / 60000);
  if (mins > 0) {
    duration = ` (${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, '0')}m)`;
  }
  const sameDay = start.day === end.day;
  return `${sameDay ? '' : `${start.day} `}${start.time} → ${sameDay ? '' : `${end.day} `}${end.time}${duration}`;
}

// Percentage chip per channel: "HR 98% ✓" (✓ good, ◐ partial, ✗ low).
function coverageChip(label, coverage, flagNote = '') {
  if (typeof coverage !== 'number' || !Number.isFinite(coverage)) {
    return `<span class="chip"><b>${label}</b> ${PATTERN_REPORT_TEXT.na}</span>`;
  }
  const pct = Math.round(coverage * 100);
  const status = coverage >= 0.95 ? '✓' : coverage >= 0.5 ? '◐' : '✗';
  return `<span class="chip"><b>${label}</b> ${pct}% ${status}${flagNote}</span>`;
}

// One metric block: header line + an axis bar where the value sits inside the
// research-plausible range (optional p5–p95-style spread shading), plus a
// caption with the observed spread. Unavailable values show an empty track.
function metricBar({ label, unit, value, range, spreadRange = null, captionExtra = '' }) {
  const [lo, hi] = range;
  const pos = v => Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100));
  const shown = fmt(value, 1);

  let track;
  if (shown === null) {
    track = `<div class="barTrack"></div><div class="metricCaption">Not available for tonight</div>`;
  } else {
    const spread = (spreadRange
      && typeof spreadRange[0] === 'number' && Number.isFinite(spreadRange[0])
      && typeof spreadRange[1] === 'number' && Number.isFinite(spreadRange[1]))
      ? `<div class="barSpread" style="left:${pos(spreadRange[0]).toFixed(1)}%;width:${Math.max(0.5, pos(spreadRange[1]) - pos(spreadRange[0])).toFixed(1)}%"></div>`
      : '';
    track = `
      <div class="barTrack">
        ${spread}
        <div class="barMark" style="left:${pos(value).toFixed(1)}%"></div>
      </div>`;
  }

  return `
    <div class="metric">
      <div class="metricHead"><span>${label}</span><span>${shown === null ? PATTERN_REPORT_TEXT.na : shown} ${unit}</span></div>
      ${track}
      <div class="metricCaption">band ${lo}–${hi} ${unit}${captionExtra ? ` · ${captionExtra}` : ''}</div>
    </div>`;
}

// Feature-value findings, in priority order. Only observation thresholds;
// lines describe the data, never the direction of care.
function findingsLines(nightly) {
  const n = nightly || {};
  const lines = [];

  const belowFrac = n.spo2_below90_frac;
  if (typeof belowFrac === 'number' && Number.isFinite(belowFrac) && belowFrac > FINDING_THRESHOLDS.desatFrac) {
    lines.push(PATTERN_REPORT_TEXT.findings.desat(fmt(belowFrac * 100, 1)));
  }

  const spo2Min = n.spo2_min;
  if (typeof spo2Min === 'number' && Number.isFinite(spo2Min) && spo2Min < FINDING_THRESHOLDS.spo2Min) {
    lines.push(PATTERN_REPORT_TEXT.findings.spo2Min(fmt(spo2Min, 0)));
  }

  const rmssd = n.rmssd_median;
  if (typeof rmssd === 'number' && Number.isFinite(rmssd) && rmssd < FINDING_THRESHOLDS.rmssdMedian) {
    lines.push(PATTERN_REPORT_TEXT.findings.rmssd(fmt(rmssd, 0)));
  }

  return lines;
}

// Channel-quality bullets for the limitations section, from payload coverage
// meta (older payloads have none → nothing extra to say).
function limitationFlags(nightly) {
  const n = nightly || {};
  const T = PATTERN_REPORT_TEXT;
  const flags = [];

  if (n.hrv_sufficient === false) flags.push(T.hrvTooShort);

  const lowChannels = [
    ['HRV', n.rmssd_coverage],
    ['SpO2', n.spo2_coverage],
    ['Heart rate', n.hr_coverage],
  ]
    .filter(([, c]) => typeof c === 'number' && Number.isFinite(c) && c < 0.5)
    .map(([name, c]) => `${name} channel had ${fmt(c * 100, 0)}% valid readings`);
  if (lowChannels.length) {
    flags.push(`${lowChannels.join(', ')} — reliability flagged.`);
  }
  return flags;
}

// ── HTML assembly ────────────────────────────────────────────────────────────

export function buildPatternReportHtml({ payload, patientName, patientId }) {
  const T = PATTERN_REPORT_TEXT;
  const now = new Date().toLocaleString();
  const n = payload?.nightly || {};
  const band = payload?.band;
  const hero = BAND_HERO[band] || { icon: '⚠', color: '#d97706' };

  // Header identity line: patient name appears on the doctor's copy.
  const patientLine = patientName
    ? ` &nbsp;·&nbsp; ${escapeHtml(patientName)}${patientId ? ` (${escapeHtml(patientId)})` : ''}`
    : '';

  const win = windowText(payload);
  const dataLine = win
    ? `Garmin recording window ${escapeHtml(win)} · ${T.deviceModel}`
    : `${T.dataSourceFallback} · ${T.deviceModel}`;

  // ── 1. Summary indicator (hero) ──
  const score = typeof payload?.p_positive === 'number' && Number.isFinite(payload.p_positive)
    ? payload.p_positive
    : null;
  const scorePct = score === null ? null : Math.max(1, Math.round(score * 100));
  const thresholdNote = typeof payload?.thresholdFlagged === 'boolean'
    ? (payload.thresholdFlagged ? T.thresholdFlagged : T.thresholdClean)
    : null;

  const heroHtml = `
    <h2>${T.sections.hero}</h2>
    <div class="hero" style="border-left:5px solid ${hero.color}">
      <div class="heroIcon" style="color:${hero.color}">${hero.icon}</div>
      <div class="heroBody">
        <div class="heroBand" style="color:${hero.color}">${escapeHtml(aiBandLabel(band))}</div>
        <div class="heroDesc">${escapeHtml(aiBandDescription(band))}</div>
        ${score === null
          ? `<div class="scoreNa">${T.scoreLabel}: ${T.na}</div>`
          : `
        <div class="scoreHead">
          <span>${T.scoreLabel}</span>
          <span><b>${fmt(score, 2)}</b> / 1.00</span>
        </div>
        <div class="scoreTrack"><div class="scoreFill" style="width:${scorePct}%"></div></div>
        ${thresholdNote ? `<div class="scoreNote">${thresholdNote}</div>` : ''}
        <div class="scoreNote">${T.scoreNote}</div>`}
      </div>
    </div>`;

  // ── 2. Sleep overview (payload features only) ──
  const dipsPct = (typeof n.spo2_below90_frac === 'number' && Number.isFinite(n.spo2_below90_frac))
    ? `${fmt(n.spo2_below90_frac * 100, 1)}%`
    : PATTERN_REPORT_TEXT.na;
  const hrCaption = (fmt(n.hr_p5, 0) !== null && fmt(n.hr_p95, 0) !== null)
    ? `observed range (p5–p95) ${fmt(n.hr_p5, 0)}–${fmt(n.hr_p95, 0)} bpm`
    : 'observed median only';
  const spo2Caption = (fmt(n.spo2_min, 0) !== null)
    ? `lowest ${fmt(n.spo2_min, 0)}% · readings below 90%: ${dipsPct}`
    : `readings below 90%: ${dipsPct}`;

  const rmssdValue = n.hrv_sufficient === false ? null : n.rmssd_median;
  const rmssdChipNote = n.hrv_sufficient === false ? ` · ${T.hrvTooShort}` : '';

  const overviewHtml = `
    <h2>${T.sections.overview}</h2>
    <div class="card">
      <div class="row2">
        <div><span class="rowLabel">Recording window</span><span class="rowValue">${win ? escapeHtml(win) : T.na}</span></div>
        <div><span class="rowLabel">Total sleep time</span><span class="rowValue">${T.noSleepStaging}</span></div>
      </div>
      ${metricBar({
        label: 'Heart rate (median)', unit: 'bpm',
        value: n.hr_median, range: METRIC_RANGES.hr,
        spreadRange: (fmt(n.hr_p5, 0) !== null && fmt(n.hr_p95, 0) !== null) ? [n.hr_p5, n.hr_p95] : null,
        captionExtra: hrCaption,
      })}
      ${metricBar({
        label: 'HRV – RMSSD (median)', unit: 'ms',
        value: rmssdValue, range: METRIC_RANGES.rmssd,
      })}
      ${metricBar({
        label: 'SpO2 (median)', unit: '%',
        value: n.spo2_median, range: METRIC_RANGES.spo2,
        captionExtra: spo2Caption,
      })}
      <div class="metricNote"><span class="rowLabel">Breathing / effort</span>${T.noBreathing}</div>
      <div class="chips">
        ${coverageChip('HR', n.hr_coverage)}
        ${coverageChip('SpO2', n.spo2_coverage)}
        ${coverageChip('HRV', n.rmssd_coverage, rmssdChipNote)}
      </div>
    </div>`;

  // ── 3. Pattern findings ──
  const lines = findingsLines(n);
  const findingsHtml = `
    <h2>${T.sections.findings}</h2>
    <div class="card">
      ${lines.length
        ? `<ul class="findings">${lines.map(l => `<li>${escapeHtml(l)}</li>`).join('')}</ul>`
        : `<p class="findingsEmpty">${T.findingsEmpty}</p>`}
      <p class="footnote">${T.findingsNote}</p>
    </div>`;

  // ── 4. Suggested next steps (tier-driven) ──
  const nextStep = patternNextStep(band) || T.na;
  const nextHtml = `
    <h2>${T.sections.nextSteps}</h2>
    <div class="card"><p class="nextStep">${escapeHtml(nextStep)}</p></div>`;

  // ── 5. Limitations & data quality ──
  const flags = limitationFlags(n);
  const limitationsHtml = `
    <h2>${T.sections.limitations}</h2>
    <div class="card">
      <ul class="limitations">
        ${flags.map(f => `<li>${escapeHtml(f)}</li>`).join('')}
        ${T.limitations.map(l => `<li>${escapeHtml(l)}</li>`).join('')}
      </ul>
    </div>`;

  // ── 6. Disclaimer (short line always visible, full block collapsible) ──
  const disclaimerHtml = `
    <h2>${T.sections.disclaimer}</h2>
    <div class="card">
      <p class="disclaimerInline">${DISCLAIMER.footer}</p>
      <details>
        <summary>${T.readDisclaimer}</summary>
        <ul>
          ${DISCLAIMER.about.bullets.map(b => `<li>${escapeHtml(aboutBulletText(b))}</li>`).join('')}
        </ul>
        <p class="closing">${escapeHtml(DISCLAIMER.about.closing)}</p>
      </details>
    </div>`;

  return `
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; color: #1a1a2e; padding: 40px; }
  h1 { font-size: 26px; color: #1a1a2e; margin-bottom: 4px; }
  .tagline { font-size: 13px; color: #666; margin-bottom: 22px; }
  .dataSource { font-size: 12px; color: #666; margin-bottom: 8px; }
  .experimentalNote { font-size: 11px; color: #b45309; background: #fef3c7; border-radius: 6px; padding: 8px 10px; margin-bottom: 10px; display: inline-block; }
  h2 { font-size: 13px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; margin: 24px 0 10px; }
  .card { border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px; }
  .hero { display: flex; gap: 14px; border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px; }
  .heroIcon { font-size: 26px; line-height: 1; padding-top: 2px; }
  .heroBody { flex: 1; }
  .heroBand { font-size: 18px; font-weight: 700; margin-bottom: 2px; }
  .heroDesc { font-size: 12px; color: #555; margin-bottom: 10px; }
  .scoreHead { display: flex; justify-content: space-between; font-size: 12px; color: #555; margin-bottom: 4px; }
  .scoreTrack { height: 10px; background: #f3f4f6; border-radius: 5px; overflow: hidden; }
  .scoreFill { height: 100%; background: #818cf8; border-radius: 5px; }
  .scoreNote { font-size: 10px; color: #888; margin-top: 4px; }
  .scoreNa { font-size: 12px; color: #888; }
  .row2 { display: flex; gap: 12px; margin-bottom: 10px; }
  .row2 > div { flex: 1; }
  .rowLabel { display: block; font-size: 10px; color: #888; text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 2px; }
  .rowValue { display: block; font-size: 14px; font-weight: 600; }
  .metric { margin-top: 12px; }
  .metricNote { margin-top: 12px; font-size: 12px; color: #555; }
  .metricHead { display: flex; justify-content: space-between; font-size: 12px; color: #333; margin-bottom: 3px; }
  .barTrack { position: relative; height: 8px; background: #f3f4f6; border-radius: 4px; }
  .barSpread { position: absolute; top: 0; bottom: 0; background: #c7d2fe; }
  .barMark { position: absolute; top: -2px; bottom: -2px; margin-left: -3px; width: 6px; background: #1a1a2e; border-radius: 3px; }
  .metricCaption { font-size: 10px; color: #888; margin-top: 3px; }
  .chips { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
  .chip { font-size: 10px; background: #f3f4f6; border-radius: 6px; padding: 4px 8px; color: #555; }
  .findings { padding-left: 18px; }
  .findings li { font-size: 12.5px; margin-bottom: 6px; }
  .findingsEmpty { font-size: 12.5px; color: #555; }
  .footnote { font-size: 10px; color: #888; margin-top: 10px; }
  .nextStep { font-size: 13px; line-height: 19px; }
  .limitations { padding-left: 18px; }
  .limitations li { font-size: 11px; color: #555; margin-bottom: 6px; }
  .disclaimerInline { font-size: 11px; color: #b45309; margin-bottom: 10px; }
  details summary { font-size: 12px; color: #818cf8; font-weight: 600; cursor: pointer; }
  details ul { padding-left: 18px; margin: 10px 0; }
  details li { font-size: 11px; color: #555; margin-bottom: 5px; }
  .closing { font-size: 11px; color: #555; }
  .footer { margin-top: 40px; font-size: 10px; color: #aaa; text-align: center; line-height: 16px; }
</style>
</head>
<body>

<h1>${T.title}</h1>
<p class="tagline">${T.researchTag} · Report ID ${escapeHtml(reportIdFrom(payload))} · Generated: ${now}${patientLine}</p>
<p class="dataSource"><b>${T.sections.data}:</b> ${dataLine}</p>
<p class="experimentalNote">${T.experimentalNote}</p>

${heroHtml}
${overviewHtml}
${findingsHtml}
${nextHtml}
${limitationsHtml}
${disclaimerHtml}

<div class="footer">${DISCLAIMER.footer}<br/>${escapeHtml(T.versionLine(payload))}</div>
</body>
</html>`;
}

export async function exportPatternReport({ payload, patientName, patientId }) {
  if (!payload || !payload.band) {
    throw new Error('Nightly analysis is not available yet.');
  }
  const html = buildPatternReportHtml({ payload, patientName, patientId });
  const { uri } = await Print.printToFileAsync({ html, base64: false });
  await Sharing.shareAsync(uri, {
    mimeType: 'application/pdf',
    dialogTitle: 'Share Sleep Pattern Report',
    UTI: 'com.adobe.pdf',
  });
}
