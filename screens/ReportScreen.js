import {
  View, Text, StyleSheet,
  ScrollView, TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';
import { useState } from 'react';
import { useSleep } from '../context/SleepContext';

export default function ReportScreen() {
  const { sessionStats, currentData, sleepTimeline } = useSleep();
  const [exporting, setExporting] = useState(false);

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

  const tiers = [
    {
      name:    'Critical',
      color:   '#ef4444',
      count:   sessionStats.critical,
      pct:     Math.round((sessionStats.critical / total) * 100),
    },
    {
      name:    'Important',
      color:   '#f59e0b',
      count:   sessionStats.important,
      pct:     Math.round((sessionStats.important / total) * 100),
    },
    {
      name:    'Normal',
      color:   '#22c55e',
      count:   sessionStats.normal,
      pct:     Math.round((sessionStats.normal / total) * 100),
    },
    {
      name:    'Background',
      color:   '#6b7280',
      count:   sessionStats.background,
      pct:     Math.round((sessionStats.background / total) * 100),
    },
  ];

  async function handleExportPdf() {
    setExporting(true);
    try {
      const now = new Date().toLocaleString();
      const timelineRows = sleepTimeline.map((d, i) => `
        <tr style="background:${i % 2 === 0 ? '#f9f9f9' : '#fff'}">
          <td>${d.time}</td>
          <td style="color:${d.spo2 < 90 ? '#dc2626' : d.spo2 < 95 ? '#d97706' : '#16a34a'};font-weight:600">${d.spo2}%</td>
          <td>${d.heartRate} bpm</td>
          <td>${d.hrv}</td>
          <td style="color:${d.tier === 'Critical' ? '#dc2626' : d.tier === 'Important' ? '#d97706' : '#16a34a'}">${d.tier}</td>
        </tr>`).join('');

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
<p class="subtitle">Generated: ${now} &nbsp;·&nbsp; ${sessionStats.total} total readings</p>

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

<div class="footer">Sleep Monitor · Auto-generated report · For clinical review only</div>
</body>
</html>`;

      const { uri } = await Print.printToFileAsync({ html, base64: false });
      await Sharing.shareAsync(uri, {
        mimeType: 'application/pdf',
        dialogTitle: 'Share Sleep Report',
        UTI: 'com.adobe.pdf',
      });
    } catch (e) {
      console.error('PDF export failed:', e);
    } finally {
      setExporting(false);
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.titleRow}>
          <View>
            <Text style={styles.title}>Session report</Text>
            <Text style={styles.subtitle}>
              Live session · {sessionStats.total} readings processed
            </Text>
          </View>
          <TouchableOpacity
            style={[styles.exportBtn, exporting && styles.exportBtnDisabled]}
            onPress={handleExportPdf}
            disabled={exporting}
            activeOpacity={0.75}
          >
            {exporting
              ? <ActivityIndicator size="small" color="#818cf8" />
              : <MaterialCommunityIcons name="file-pdf-box" size={18} color="#818cf8" />
            }
            <Text style={styles.exportBtnText}>
              {exporting ? 'Exporting...' : 'Export PDF'}
            </Text>
          </TouchableOpacity>
        </View>

        {/* Summary cards */}
        <View style={styles.grid}>
          <SummaryCard
            label="Critical events"
            value={sessionStats.critical}
            color="#f87171"
          />
          <SummaryCard
            label="Important events"
            value={sessionStats.important}
            color="#fbbf24"
          />
          <SummaryCard
            label="Current SpO2"
            value={`${currentData.spo2}%`}
            color={currentData.spo2 < 90 ? '#f87171' : '#4ade80'}
          />
          <SummaryCard
            label="Current HR"
            value={`${currentData.heartRate} bpm`}
            color="#9ca3af"
          />
          <SummaryCard
            label="Total readings"
            value={sessionStats.total}
            color="#818cf8"
          />
          <SummaryCard
            label="Current tier"
            value={currentData.tier}
            color="#818cf8"
          />
        </View>

        {/* Tier distribution bars */}
        <Text style={styles.sectionLabel}>Readings per tier</Text>
        <View style={styles.barsCard}>
          {tiers.map(tier => (
            <TierBar key={tier.name} tier={tier} />
          ))}
        </View>

        {/* Stacked bar */}
        <Text style={styles.sectionLabel}>Session overview</Text>
        <View style={styles.stackedCard}>
          <View style={styles.stackedBar}>
            {tiers.map(tier => (
              <View
                key={tier.name}
                style={{
                  width:           `${Math.max(tier.pct, 0)}%`,
                  height:          '100%',
                  backgroundColor: tier.color,
                }}
              />
            ))}
          </View>
          <View style={styles.stackLegend}>
            {tiers.map(t => (
              <View key={t.name} style={styles.legendItem}>
                <View style={[styles.legendDot, { backgroundColor: t.color }]} />
                <Text style={styles.legendText}>{t.name} ({t.pct}%)</Text>
              </View>
            ))}
          </View>
        </View>

        {/* QoS transmission summary */}
        <Text style={styles.sectionLabel}>QoS transmission summary</Text>
        <View style={styles.qosCard}>
          <QoSRow
            topic="sleep/critical"
            qos="QoS 2"
            count={sessionStats.critical}
            color="#f87171"
          />
          <QoSRow
            topic="sleep/important"
            qos="QoS 1"
            count={sessionStats.important}
            color="#fbbf24"
          />
          <QoSRow
            topic="sleep/normal"
            qos="QoS 0"
            count={sessionStats.normal}
            color="#4ade80"
          />
          <QoSRow
            topic="sleep/background"
            qos="QoS 0"
            count={sessionStats.background}
            color="#9ca3af"
          />
        </View>

        {/* SpO2 over session */}
        <Text style={styles.sectionLabel}>SpO2 over session</Text>
        <View style={styles.timelineCard}>
          <TimelineChart
            data={sleepTimeline}
            valueKey="spo2"
            colorFn={v => v < 90 ? '#ef4444' : v < 95 ? '#f59e0b' : '#4ade80'}
          />
        </View>

        {/* Heart rate over session */}
        <Text style={styles.sectionLabel}>Heart rate over session</Text>
        <View style={styles.timelineCard}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-around', marginBottom: 12 }}>
            <Text style={{ fontSize: 12, color: '#555' }}>
              Min <Text style={{ color: '#818cf8' }}>{hrMin}</Text>
            </Text>
            <Text style={{ fontSize: 12, color: '#555' }}>
              Avg <Text style={{ color: '#818cf8' }}>{hrAvg}</Text>
            </Text>
            <Text style={{ fontSize: 12, color: '#555' }}>
              Max <Text style={{ color: '#818cf8' }}>{hrMax}</Text>
            </Text>
          </View>
          <TimelineChart
            data={sleepTimeline}
            valueKey="heartRate"
            barColor="#818cf8"
          />
        </View>

      </ScrollView>
    </SafeAreaView>
  );
}

function SummaryCard({ label, value, color }) {
  return (
    <View style={styles.summaryCard}>
      <Text style={styles.summaryLabel}>{label}</Text>
      <Text style={[styles.summaryValue, { color }]}>{value}</Text>
    </View>
  );
}

function TierBar({ tier }) {
  return (
    <View style={styles.barRow}>
      <View style={styles.barMeta}>
        <Text style={[styles.barName, { color: tier.color }]}>{tier.name}</Text>
        <Text style={styles.barTime}>{tier.count} readings ({tier.pct}%)</Text>
      </View>
      <View style={styles.barTrack}>
        <View style={[styles.barFill, {
          width:           `${Math.max(tier.pct, 1)}%`,
          backgroundColor: tier.color,
        }]} />
      </View>
    </View>
  );
}

function TimelineChart({ data, valueKey, colorFn, barColor, height = 80 }) {
  if (!data || data.length === 0) {
    return (
      <View style={{ height: 80, alignItems: 'center', justifyContent: 'center' }}>
        <Text style={{ fontSize: 12, color: '#555', fontStyle: 'italic' }}>
          Waiting for readings...
        </Text>
      </View>
    );
  }
  const values = data.map(d => d[valueKey]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false}>
      <View>
        <View style={{ flexDirection: 'row', alignItems: 'flex-end', height }}>
          {data.map((entry, i) => {
            const val = entry[valueKey];
            const barH = ((val - min) / range) * 100;
            const color = colorFn ? colorFn(val) : barColor;
            return (
              <View key={i} style={{ width: 6, marginRight: 2, height: '100%', justifyContent: 'flex-end' }}>
                <View style={{ height: `${Math.max(barH, 8)}%`, backgroundColor: color, borderRadius: 2 }} />
              </View>
            );
          })}
        </View>
        <View style={{ flexDirection: 'row', marginTop: 4 }}>
          {data.map((entry, i) => (
            <View key={i} style={{ width: 6, marginRight: 2 }}>
              {i % 15 === 0 && (
                <Text style={{ fontSize: 8, color: '#555', width: 36, marginLeft: -15 }} numberOfLines={1}>
                  {entry.time}
                </Text>
              )}
            </View>
          ))}
        </View>
      </View>
    </ScrollView>
  );
}

function QoSRow({ topic, qos, count, color }) {
  return (
    <View style={styles.qosRow}>
      <View style={[styles.qosDot, { backgroundColor: color }]} />
      <Text style={styles.qosTopic}>{topic}</Text>
      <Text style={styles.qosLabel}>{qos}</Text>
      <Text style={styles.qosCount}>{count} msgs</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container:    { flex: 1, backgroundColor: '#0a0a0f' },
  scroll:       { padding: 20, paddingBottom: 40 },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 22,
  },
  title:        { fontSize: 26, fontWeight: '700', color: '#fff', marginBottom: 4 },
  subtitle:     { fontSize: 13, color: '#555' },
  exportBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#13131f',
    borderWidth: 1,
    borderColor: '#2a2a4a',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  exportBtnDisabled: {
    opacity: 0.5,
  },
  exportBtnText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#818cf8',
  },
  sectionLabel: {
    fontSize: 11, color: '#555', marginBottom: 10,
    letterSpacing: 0.5, textTransform: 'uppercase',
  },
  grid:         { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 24 },
  summaryCard:  {
    width: '47%', backgroundColor: '#13131f',
    borderRadius: 12, padding: 14,
    borderWidth: 0.5, borderColor: '#1e1e30',
  },
  summaryLabel: { fontSize: 11, color: '#666', marginBottom: 6 },
  summaryValue: { fontSize: 22, fontWeight: '700' },
  barsCard:     {
    backgroundColor: '#13131f', borderRadius: 12,
    padding: 16, marginBottom: 22,
    borderWidth: 0.5, borderColor: '#1e1e30', gap: 14,
  },
  barRow:       { gap: 6 },
  barMeta:      { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 },
  barName:      { fontSize: 12, fontWeight: '600' },
  barTime:      { fontSize: 12, color: '#555' },
  barTrack:     { height: 6, backgroundColor: '#1a1a2e', borderRadius: 3, overflow: 'hidden' },
  barFill:      { height: '100%', borderRadius: 3 },
  stackedCard:  {
    backgroundColor: '#13131f', borderRadius: 12,
    padding: 16, marginBottom: 22,
    borderWidth: 0.5, borderColor: '#1e1e30',
  },
  stackedBar:   {
    height: 20, borderRadius: 6,
    flexDirection: 'row', overflow: 'hidden', marginBottom: 12,
  },
  stackLegend:  { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  legendItem:   { flexDirection: 'row', alignItems: 'center', gap: 5 },
  legendDot:    { width: 7, height: 7, borderRadius: 4 },
  legendText:   { fontSize: 11, color: '#888' },
  qosCard:      {
    backgroundColor: '#13131f', borderRadius: 12,
    padding: 16, borderWidth: 0.5,
    borderColor: '#1e1e30', gap: 12,
  },
  qosRow:       { flexDirection: 'row', alignItems: 'center', gap: 8 },
  qosDot:       { width: 7, height: 7, borderRadius: 4 },
  qosTopic:     { fontSize: 12, color: '#ccc', flex: 1, fontFamily: 'monospace' },
  qosLabel:     {
    fontSize: 10, color: '#555', backgroundColor: '#1a1a2e',
    paddingVertical: 2, paddingHorizontal: 6, borderRadius: 6,
  },
  qosCount:     { fontSize: 11, color: '#555', minWidth: 50, textAlign: 'right' },
  timelineCard: {
    backgroundColor: '#13131f',
    borderRadius: 12,
    padding: 16,
    marginBottom: 22,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    overflow: 'hidden',
  },
});