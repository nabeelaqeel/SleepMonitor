import React from 'react';
import {
  View, Text, StyleSheet,
  ScrollView, SafeAreaView,
} from 'react-native';
import { useSleep } from '../context/SleepContext';

export default function ReportScreen() {
  const { sessionStats, currentData } = useSleep();

  const total = sessionStats.total || 1;

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

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        <Text style={styles.title}>Session report</Text>
        <Text style={styles.subtitle}>
          Live session · {sessionStats.total} readings processed
        </Text>

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
  title:        { fontSize: 26, fontWeight: '700', color: '#fff', marginBottom: 4 },
  subtitle:     { fontSize: 13, color: '#555', marginBottom: 22 },
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
});