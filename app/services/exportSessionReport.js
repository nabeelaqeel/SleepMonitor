import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';
import { DISCLAIMER } from '../config/displayText';
import { pdfBaseName } from './saveToDevice';

// Builds the sleep-session report as an HTML document and renders it to a PDF.
//
// buildSessionReportPdf() returns the temp file URI + export name so the
// callers choose delivery themselves: sharing to WhatsApp/mail via
// exportSessionReport(), or a silent download via services/saveToDevice.
// Shared by the patient's Report tab and the doctor's patient detail screen:
// both export the same live session, but the doctor's copy names the patient
// it belongs to through the optional patientName / patientId.
export async function buildSessionReportPdf({
  sessionStats,
  currentData,
  sleepTimeline,
  patientName,
  patientId,
}) {
  const now = new Date().toLocaleString();
  const total = sessionStats.total || 1;

  const hrValues = sleepTimeline.map(d => d.heartRate);
  const hrMin = hrValues.length ? Math.min(...hrValues) : '--';
  const hrMax = hrValues.length ? Math.max(...hrValues) : '--';
  const hrAvg = hrValues.length
    ? Math.round(hrValues.reduce((a, b) => a + b, 0) / hrValues.length)
    : '--';

  const spo2Values = sleepTimeline.map(d => d.spo2);
  const spo2Min = spo2Values.length ? Math.min(...spo2Values) : '--';
  const spo2Max = spo2Values.length ? Math.max(...spo2Values) : '--';
  const spo2Avg = spo2Values.length
    ? (spo2Values.reduce((a, b) => a + b, 0) / spo2Values.length).toFixed(1)
    : '--';

  const timelineRows = sleepTimeline.map((d, i) => `
        <tr style="background:${i % 2 === 0 ? '#f9f9f9' : '#fff'}">
          <td>${d.time}</td>
          <td style="color:${d.spo2 < 90 ? '#dc2626' : d.spo2 < 95 ? '#d97706' : '#16a34a'};font-weight:600">${d.spo2}%</td>
          <td>${d.heartRate} bpm</td>
          <td>${d.hrv}</td>
          <td style="color:${d.tier === 'Critical' ? '#dc2626' : d.tier === 'Important' ? '#d97706' : '#16a34a'}">${d.tier}</td>
        </tr>`).join('');

  // Shown next to the timestamp when the caller passes a patient (doctor copy).
  const patientLine = patientName
    ? ` &nbsp;·&nbsp; ${patientName}${patientId ? ` (${patientId})` : ''}`
    : '';

  const html = `
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; color: #1a1a2e; padding: 40px; }
  h1 { font-size: 26px; color: #1a1a2e; margin-bottom: 4px; }
  .subtitle { font-size: 13px; color: #666; margin-bottom: 30px; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
  .badge-critical { background: #fee2e2; color: #dc2626; }
  .badge-important { background: #fef3c7; color: #d97706; }
  .badge-normal { background: #dcfce7; color: #16a34a; }
  h2 { font-size: 13px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; margin: 24px 0 10px; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  .card { border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px; }
  .card-label { font-size: 11px; color: #888; margin-bottom: 5px; }
  .card-value { font-size: 22px; font-weight: 700; }
  .color-critical { color: #dc2626; }
  .color-important { color: #d97706; }
  .color-normal { color: #16a34a; }
  .color-indigo { color: #4f46e5; }
  .color-gray { color: #6b7280; }
  .bar-row { margin-bottom: 10px; }
  .bar-label { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px; }
  .bar-track { height: 8px; background: #f3f4f6; border-radius: 4px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 6px; }
  th { background: #f3f4f6; padding: 8px 10px; text-align: left; font-size: 11px; color: #555; text-transform: uppercase; letter-spacing: 0.3px; }
  td { padding: 8px 10px; border-bottom: 1px solid #f3f4f6; }
  .footer { margin-top: 40px; font-size: 11px; color: #aaa; text-align: center; }
  .divider { height: 1px; background: #f3f4f6; margin: 28px 0; }
</style>
</head>
<body>

<h1>Sleep Session Report</h1>
<p class="subtitle">Generated: ${now} &nbsp;·&nbsp; ${sessionStats.total} total readings${patientLine}</p>

<h2>Session Summary</h2>
<div class="grid">
  <div class="card">
    <div class="card-label">Critical Events</div>
    <div class="card-value color-critical">${sessionStats.critical}</div>
  </div>
  <div class="card">
    <div class="card-label">Important Events</div>
    <div class="card-value color-important">${sessionStats.important}</div>
  </div>
  <div class="card">
    <div class="card-label">Normal Readings</div>
    <div class="card-value color-normal">${sessionStats.normal}</div>
  </div>
  <div class="card">
    <div class="card-label">SpO2 Min / Avg / Max</div>
    <div class="card-value color-indigo" style="font-size:16px">${spo2Min}% / ${spo2Avg}% / ${spo2Max}%</div>
  </div>
  <div class="card">
    <div class="card-label">Heart Rate Min / Avg / Max</div>
    <div class="card-value color-indigo" style="font-size:16px">${hrMin} / ${hrAvg} / ${hrMax} bpm</div>
  </div>
  <div class="card">
    <div class="card-label">Current Tier</div>
    <div class="card-value" style="font-size:16px">
      <span class="badge badge-${currentData.tier.toLowerCase()}">${currentData.tier}</span>
    </div>
  </div>
</div>

<h2>Tier Distribution</h2>
<div class="bar-row">
  <div class="bar-label"><span style="color:#dc2626;font-weight:600">Critical</span><span>${sessionStats.critical} readings (${Math.round((sessionStats.critical/total)*100)}%)</span></div>
  <div class="bar-track"><div class="bar-fill" style="width:${Math.max(Math.round((sessionStats.critical/total)*100),1)}%;background:#dc2626"></div></div>
</div>
<div class="bar-row">
  <div class="bar-label"><span style="color:#d97706;font-weight:600">Important</span><span>${sessionStats.important} readings (${Math.round((sessionStats.important/total)*100)}%)</span></div>
  <div class="bar-track"><div class="bar-fill" style="width:${Math.max(Math.round((sessionStats.important/total)*100),1)}%;background:#d97706"></div></div>
</div>
<div class="bar-row">
  <div class="bar-label"><span style="color:#16a34a;font-weight:600">Normal</span><span>${sessionStats.normal} readings (${Math.round((sessionStats.normal/total)*100)}%)</span></div>
  <div class="bar-track"><div class="bar-fill" style="width:${Math.max(Math.round((sessionStats.normal/total)*100),1)}%;background:#16a34a"></div></div>
</div>
<div class="bar-row">
  <div class="bar-label"><span style="color:#6b7280;font-weight:600">Background</span><span>${sessionStats.background} readings (${Math.round((sessionStats.background/total)*100)}%)</span></div>
  <div class="bar-track"><div class="bar-fill" style="width:${Math.max(Math.round((sessionStats.background/total)*100),1)}%;background:#6b7280"></div></div>
</div>

<h2>QoS Transmission Summary</h2>
<table>
  <tr><th>Topic</th><th>QoS Level</th><th>Messages</th></tr>
  <tr><td>sleep/critical</td><td>QoS 2 — Exactly once</td><td>${sessionStats.critical}</td></tr>
  <tr style="background:#f9f9f9"><td>sleep/important</td><td>QoS 1 — At least once</td><td>${sessionStats.important}</td></tr>
  <tr><td>sleep/normal</td><td>QoS 0 — Best effort</td><td>${sessionStats.normal}</td></tr>
  <tr style="background:#f9f9f9"><td>sleep/background</td><td>QoS 0 — Best effort</td><td>${sessionStats.background}</td></tr>
</table>

${sleepTimeline.length > 0 ? `
<div class="divider"></div>
<h2>Reading Timeline (last ${sleepTimeline.length} entries)</h2>
<table>
  <tr><th>Time</th><th>SpO2</th><th>Heart Rate</th><th>HRV</th><th>Tier</th></tr>
  ${timelineRows}
</table>` : ''}

<div class="footer">${DISCLAIMER.footer}<br/>Sleep Monitor · Auto-generated report</div>
</body>
</html>`;

  const { uri } = await Print.printToFileAsync({ html, base64: false });
  return { uri, name: pdfBaseName('SessionReport') };
}

// Renders the report and hands it to the OS share sheet (WhatsApp, mail, …).
export async function exportSessionReport(args) {
  const { uri } = await buildSessionReportPdf(args);
  await shareSessionReport(uri);
}

export async function shareSessionReport(uri) {
  await Sharing.shareAsync(uri, {
    mimeType: 'application/pdf',
    dialogTitle: 'Share Sleep Report',
    UTI: 'com.adobe.pdf',
  });
}
