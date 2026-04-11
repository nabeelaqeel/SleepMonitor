import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  SafeAreaView,
} from 'react-native';

const MOCK_REPORT = {
  date: 'Last night',
  duration: '7h 12m',
  avgSpo2: 95.2,
  minSpo2: 87,
  avgHr: 54,
  criticalEvents: 3,
  importantEvents: 2,
  tiers: [
    { name: 'Critical',   color: '#ef4444', minutes: 4,   totalMinutes: 432 },
    { name: 'Important',  color: '#f59e0b', minutes: 22,  totalMinutes: 432 },
    { name: 'Normal',     color: '#22c55e', minutes: 390, totalMinutes: 432 },
    { name: 'Background', color: '#6b7280', minutes: 16,  totalMinutes: 432 },
  ],
};

export default function ReportScreen() {
  const report = MOCK_REPORT;

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        {/* Header */}
        <Text style={styles.title}>Sleep report</Text>
        <Text style={styles.subtitle}>
          {report.date} — {report.duration}
        </Text>

        {/* Summary cards */}
        <View style={styles.grid}>
          <SummaryCard
            label="Critical events"
            value={report.criticalEvents}
            color="#f87171"
          />
          <SummaryCard
            label="Important events"
            value={report.importantEvents}
            color="#fbbf24"
          />
          <SummaryCard
            label="Avg SpO2"
            value={`${report.avgSpo2}%`}
            color="#4ade80"
          />
          <SummaryCard
            label="Min SpO2"
            value={`${report.minSpo2}%`}
            color="#f87171"
          />
          <SummaryCard
            label="Avg heart rate"
            value={`${report.avgHr} bpm`}
            color="#9ca3af"
          />
          <SummaryCard
            label="Total sleep"
            value={report.duration}
            color="#818cf8"
          />
        </View>

        {/* Tier distribution */}
        <Text style={styles.sectionLabel}>Time in each tier</Text>
        <View style={styles.barsCard}>
          {report.tiers.map(tier => (
            <TierBar key={tier.name} tier={tier} />
          ))}
        </View>

        {/* Overall stacked bar */}
        <Text style={styles.sectionLabel}>Night overview</Text>
        <View style={styles.stackedCard}>
          <StackedBar tiers={report.tiers} />
          <View style={styles.stackLegend}>
            {report.tiers.map(t => (
              <View key={t.name} style={styles.legendItem}>
                <View style={[styles.legendDot, { backgroundColor: t.color }]} />
                <Text style={styles.legendText}>{t.name}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* QoS summary */}
        <Text style={styles.sectionLabel}>QoS transmission summary</Text>
        <View style={styles.qosCard}>
          <QoSRow topic="sleep/critical"    qos="QoS 2" count={3}   color="#f87171" />
          <QoSRow topic="sleep/important"   qos="QoS 1" count={2}   color="#fbbf24" />
          <QoSRow topic="sleep/normal"      qos="QoS 0" count={390} color="#4ade80" />
          <QoSRow topic="sleep/background"  qos="QoS 0" count={16}  color="#9ca3af" />
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
  const pct = Math.round((tier.minutes / tier.totalMinutes) * 100);
  const displayTime = tier.minutes >= 60
    ? `${Math.floor(tier.minutes / 60)}h ${tier.minutes % 60}m`
    : `${tier.minutes} min`;

  return (
    <View style={styles.barRow}>
      <View style={styles.barMeta}>
        <Text style={[styles.barName, { color: tier.color }]}>{tier.name}</Text>
        <Text style={styles.barTime}>{displayTime}</Text>
      </View>
      <View style={styles.barTrack}>
        <View style={[styles.barFill, {
          width: `${Math.max(pct, 1)}%`,
          backgroundColor: tier.color,
        }]} />
      </View>
    </View>
  );
}

function StackedBar({ tiers }) {
  return (
    <View style={styles.stackedBar}>
      {tiers.map(tier => {
        const pct = (tier.minutes / tier.totalMinutes) * 100;
        return (
          <View
            key={tier.name}
            style={{
              width: `${pct}%`,
              height: '100%',
              backgroundColor: tier.color,
            }}
          />
        );
      })}
    </View>
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
  container:     { flex: 1, backgroundColor: '#0a0a0f' },
  scroll:        { padding: 20, paddingBottom: 40 },

  title:         { fontSize: 26, fontWeight: '700', color: '#fff', marginBottom: 4 },
  subtitle:      { fontSize: 13, color: '#555', marginBottom: 22 },

  sectionLabel:  {
    fontSize: 11, color: '#555', marginBottom: 10,
    letterSpacing: 0.5, textTransform: 'uppercase',
  },

  grid:          {
    flexDirection: 'row', flexWrap: 'wrap',
    gap: 10, marginBottom: 24,
  },
  summaryCard:   {
    width: '47%',
    backgroundColor: '#13131f',
    borderRadius: 12,
    padding: 14,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
  },
  summaryLabel:  { fontSize: 11, color: '#666', marginBottom: 6 },
  summaryValue:  { fontSize: 22, fontWeight: '700' },

  barsCard:      {
    backgroundColor: '#13131f',
    borderRadius: 12,
    padding: 16,
    marginBottom: 22,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    gap: 14,
  },
  barRow:        { gap: 6 },
  barMeta:       {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  barName:       { fontSize: 12, fontWeight: '600' },
  barTime:       { fontSize: 12, color: '#555' },
  barTrack:      {
    height: 6,
    backgroundColor: '#1a1a2e',
    borderRadius: 3,
    overflow: 'hidden',
  },
  barFill:       { height: '100%', borderRadius: 3 },

  stackedCard:   {
    backgroundColor: '#13131f',
    borderRadius: 12,
    padding: 16,
    marginBottom: 22,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
  },
  stackedBar:    {
    height: 20,
    borderRadius: 6,
    flexDirection: 'row',
    overflow: 'hidden',
    marginBottom: 12,
  },
  stackLegend:   {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  legendItem:    { flexDirection: 'row', alignItems: 'center', gap: 5 },
  legendDot:     { width: 7, height: 7, borderRadius: 4 },
  legendText:    { fontSize: 11, color: '#888' },

  qosCard:       {
    backgroundColor: '#13131f',
    borderRadius: 12,
    padding: 16,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    gap: 12,
  },
  qosRow:        {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  qosDot:        { width: 7, height: 7, borderRadius: 4 },
  qosTopic:      { fontSize: 12, color: '#ccc', flex: 1, fontFamily: 'monospace' },
  qosLabel:      {
    fontSize: 10, color: '#555',
    backgroundColor: '#1a1a2e',
    paddingVertical: 2,
    paddingHorizontal: 6,
    borderRadius: 6,
  },
  qosCount:      { fontSize: 11, color: '#555', minWidth: 50, textAlign: 'right' },
});