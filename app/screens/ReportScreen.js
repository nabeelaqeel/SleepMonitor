import {
  View, Text, StyleSheet,
  ScrollView, TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useState } from 'react';
import { useSleep } from '../context/SleepContext';
import { exportSessionReport } from '../services/exportSessionReport';
import { tierShortLabel, topicDisplayLabel } from '../config/displayText';

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

  // Legend names come from the centralized display labels; the underlying
  // sessionStats keys (critical / important / normal / background) stay as-is.
  const tiers = [
    {
      name:    tierShortLabel('Critical'),
      color:   '#ef4444',
      count:   sessionStats.critical,
      pct:     Math.round((sessionStats.critical / total) * 100),
    },
    {
      name:    tierShortLabel('Important'),
      color:   '#f59e0b',
      count:   sessionStats.important,
      pct:     Math.round((sessionStats.important / total) * 100),
    },
    {
      name:    tierShortLabel('Normal'),
      color:   '#22c55e',
      count:   sessionStats.normal,
      pct:     Math.round((sessionStats.normal / total) * 100),
    },
    {
      name:    tierShortLabel('Background'),
      color:   '#6b7280',
      count:   sessionStats.background,
      pct:     Math.round((sessionStats.background / total) * 100),
    },
  ];

  async function handleExportPdf() {
    setExporting(true);
    try {
      await exportSessionReport({ sessionStats, currentData, sleepTimeline });
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
            label={`${tierShortLabel('Critical')} events`}
            value={sessionStats.critical}
            color="#f87171"
          />
          <SummaryCard
            label={`${tierShortLabel('Important')} events`}
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
            value={tierShortLabel(currentData.tier)}
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
            topic={topicDisplayLabel('sleep/critical')}
            qos="QoS 2"
            count={sessionStats.critical}
            color="#f87171"
          />
          <QoSRow
            topic={topicDisplayLabel('sleep/important')}
            qos="QoS 1"
            count={sessionStats.important}
            color="#fbbf24"
          />
          <QoSRow
            topic={topicDisplayLabel('sleep/normal')}
            qos="QoS 0"
            count={sessionStats.normal}
            color="#4ade80"
          />
          <QoSRow
            topic={topicDisplayLabel('sleep/background')}
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