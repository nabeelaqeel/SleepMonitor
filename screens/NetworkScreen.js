import React from 'react';
import {
  View, Text, StyleSheet,
  ScrollView, SafeAreaView,
} from 'react-native';
import { useSleep } from '../context/SleepContext';

export default function NetworkScreen() {
  const { networkStats, sessionStats } = useSleep();

  const totalMessages = sessionStats.total || 0;

  const topics = [
    {
      name:      'sleep/critical',
      qos:       2,
      qosLabel:  'QoS 2 — guaranteed',
      count:     networkStats.critical?.count  || 0,
      latency:   networkStats.critical?.latency || 0,
      delivery:  100,
      color:     '#f87171',
      badgeBg:   '#3d1010',
    },
    {
      name:      'sleep/important',
      qos:       1,
      qosLabel:  'QoS 1 — at least once',
      count:     networkStats.important?.count  || 0,
      latency:   networkStats.important?.latency || 0,
      delivery:  98,
      color:     '#fbbf24',
      badgeBg:   '#2d1f07',
    },
    {
      name:      'sleep/normal',
      qos:       0,
      qosLabel:  'QoS 0 — best effort',
      count:     networkStats.normal?.count  || 0,
      latency:   networkStats.normal?.latency || 0,
      delivery:  91,
      color:     '#4ade80',
      badgeBg:   '#0a2010',
    },
    {
      name:      'sleep/background',
      qos:       0,
      qosLabel:  'QoS 0 — batch',
      count:     networkStats.background?.count  || 0,
      latency:   networkStats.background?.latency || 0,
      delivery:  84,
      color:     '#9ca3af',
      badgeBg:   '#1a1a1a',
    },
  ];

  const criticalLatency = networkStats.critical?.latency || 0;

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        <Text style={styles.title}>QoS network status</Text>
        <Text style={styles.subtitle}>MQTT broker monitoring</Text>

        {/* Broker status card */}
        <View style={styles.brokerCard}>
          <View style={styles.brokerTop}>
            <View>
              <Text style={styles.brokerLabel}>Broker address</Text>
              <Text style={styles.brokerAddress}>localhost:1883</Text>
            </View>
            <View style={[
              styles.statusBadge,
              { backgroundColor: networkStats.connected ? '#0a2010' : '#3d1010' }
            ]}>
              <View style={[
                styles.statusDot,
                { backgroundColor: networkStats.connected ? '#22c55e' : '#ef4444' }
              ]} />
              <Text style={[
                styles.statusText,
                { color: networkStats.connected ? '#4ade80' : '#f87171' }
              ]}>
                {networkStats.connected ? 'Connected' : 'Waiting...'}
              </Text>
            </View>
          </View>

          <View style={styles.divider} />

          {/* Summary stats */}
          <View style={styles.statRow}>
            <StatBox label="Total messages" value={totalMessages} />
            <StatBox label="Active topics"  value={4}             />
            <StatBox
              label="Critical latency"
              value={criticalLatency > 0 ? `${criticalLatency}ms` : '—'}
              color="#4ade80"
            />
          </View>
        </View>

        {/* Topic cards */}
        <Text style={styles.sectionLabel}>Topic delivery rates</Text>
        {topics.map(topic => (
          <TopicCard key={topic.name} topic={topic} />
        ))}

        {/* QoS comparison table */}
        <Text style={styles.sectionLabel}>QoS level comparison</Text>
        <View style={styles.compareCard}>
          <CompareRow
            level="QoS 2"
            color="#f87171"
            delivery="100%"
            latency="~12ms"
            useCase="Critical — apnea events"
          />
          <View style={styles.compareDivider} />
          <CompareRow
            level="QoS 1"
            color="#fbbf24"
            delivery="98%"
            latency="~28ms"
            useCase="Important — abnormal trends"
          />
          <View style={styles.compareDivider} />
          <CompareRow
            level="QoS 0"
            color="#4ade80"
            delivery="84–91%"
            latency="~45ms"
            useCase="Normal + Background data"
          />
        </View>

        {/* Why QoS matters — for your panel */}
        <Text style={styles.sectionLabel}>Why QoS matters</Text>
        <View style={styles.explainCard}>
          <ExplainRow
            level="QoS 2"
            color="#f87171"
            desc="Exactly-once delivery. Broker stores message and waits for acknowledgement. Used for life-critical apnea events."
          />
          <ExplainRow
            level="QoS 1"
            color="#fbbf24"
            desc="At least once delivery. Message may duplicate but never lost. Used for important physiological trends."
          />
          <ExplainRow
            level="QoS 0"
            color="#9ca3af"
            desc="Best effort delivery. May be dropped under network load. Acceptable for routine sleep data and statistics."
          />
        </View>

      </ScrollView>
    </SafeAreaView>
  );
}

// ── Sub-components ────────────────────────────────────

function StatBox({ label, value, color = '#ffffff' }) {
  return (
    <View style={styles.statBox}>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function TopicCard({ topic }) {
  return (
    <View style={[styles.topicCard, { borderLeftColor: topic.color }]}>
      <View style={styles.topicTop}>
        <Text style={styles.topicName}>{topic.name}</Text>
        <View style={[styles.qosBadge, { backgroundColor: topic.badgeBg }]}>
          <Text style={[styles.qosBadgeText, { color: topic.color }]}>
            {topic.qosLabel}
          </Text>
        </View>
      </View>

      <View style={styles.topicStats}>
        <TopicStat label="Messages" value={topic.count} />
        <TopicStat label="Delivery"  value={`${topic.delivery}%`} />
        <TopicStat label="Latency"   value={topic.latency > 0 ? `${topic.latency}ms` : '—'} />
      </View>

      <View style={styles.deliveryTrack}>
        <View style={[styles.deliveryFill, {
          width:           `${topic.delivery}%`,
          backgroundColor: topic.color,
        }]} />
      </View>
    </View>
  );
}

function TopicStat({ label, value }) {
  return (
    <View>
      <Text style={styles.topicStatValue}>{value}</Text>
      <Text style={styles.topicStatLabel}>{label}</Text>
    </View>
  );
}

function CompareRow({ level, color, delivery, latency, useCase }) {
  return (
    <View style={styles.compareRow}>
      <View style={[styles.levelBadge, { backgroundColor: color + '20' }]}>
        <Text style={[styles.levelText, { color }]}>{level}</Text>
      </View>
      <View style={styles.compareDetails}>
        <Text style={styles.compareUseCase}>{useCase}</Text>
        <View style={styles.compareMetrics}>
          <Text style={styles.compareMetric}>Delivery: {delivery}</Text>
          <Text style={styles.compareMetric}>Latency: {latency}</Text>
        </View>
      </View>
    </View>
  );
}

function ExplainRow({ level, color, desc }) {
  return (
    <View style={styles.explainRow}>
      <View style={[styles.explainBadge, { backgroundColor: color + '20' }]}>
        <Text style={[styles.explainLevel, { color }]}>{level}</Text>
      </View>
      <Text style={styles.explainDesc}>{desc}</Text>
    </View>
  );
}

// ── Styles ────────────────────────────────────────────

const styles = StyleSheet.create({
  container:       { flex: 1, backgroundColor: '#0a0a0f' },
  scroll:          { padding: 20, paddingBottom: 40 },
  title:           { fontSize: 26, fontWeight: '700', color: '#fff', marginBottom: 4 },
  subtitle:        { fontSize: 13, color: '#555', marginBottom: 22 },
  sectionLabel:    {
    fontSize: 11, color: '#555', marginBottom: 10,
    letterSpacing: 0.5, textTransform: 'uppercase',
  },

  brokerCard:      {
    backgroundColor: '#13131f', borderRadius: 14,
    padding: 16, marginBottom: 24,
    borderWidth: 0.5, borderColor: '#1e1e30',
  },
  brokerTop:       {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
  },
  brokerLabel:     { fontSize: 11, color: '#555', marginBottom: 4 },
  brokerAddress:   { fontSize: 14, color: '#e5e5e5', fontFamily: 'monospace' },
  statusBadge:     {
    flexDirection: 'row', alignItems: 'center',
    gap: 6, paddingVertical: 6,
    paddingHorizontal: 10, borderRadius: 20,
  },
  statusDot:       { width: 7, height: 7, borderRadius: 4 },
  statusText:      { fontSize: 12, fontWeight: '600' },
  divider:         { height: 0.5, backgroundColor: '#1e1e30', marginVertical: 14 },
  statRow:         { flexDirection: 'row', justifyContent: 'space-around' },
  statBox:         { alignItems: 'center' },
  statValue:       { fontSize: 20, fontWeight: '700', color: '#fff', marginBottom: 3 },
  statLabel:       { fontSize: 10, color: '#555', textAlign: 'center' },

  topicCard:       {
    backgroundColor: '#13131f', borderRadius: 12,
    padding: 14, marginBottom: 10,
    borderLeftWidth: 2.5, borderWidth: 0.5, borderColor: '#1e1e30',
  },
  topicTop:        {
    flexDirection: 'row', justifyContent: 'space-between',
    alignItems: 'center', marginBottom: 12,
    flexWrap: 'wrap', gap: 6,
  },
  topicName:       { fontSize: 13, color: '#e5e5e5', fontFamily: 'monospace', fontWeight: '600' },
  qosBadge:        { borderRadius: 10, paddingVertical: 3, paddingHorizontal: 8 },
  qosBadgeText:    { fontSize: 10, fontWeight: '600' },
  topicStats:      { flexDirection: 'row', gap: 24, marginBottom: 10 },
  topicStatValue:  { fontSize: 16, fontWeight: '700', color: '#fff', marginBottom: 2 },
  topicStatLabel:  { fontSize: 10, color: '#555' },
  deliveryTrack:   {
    height: 4, backgroundColor: '#1a1a2e',
    borderRadius: 2, overflow: 'hidden',
  },
  deliveryFill:    { height: '100%', borderRadius: 2 },

  compareCard:     {
    backgroundColor: '#13131f', borderRadius: 12,
    padding: 16, marginBottom: 22,
    borderWidth: 0.5, borderColor: '#1e1e30',
  },
  compareRow:      { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8 },
  compareDivider:  { height: 0.5, backgroundColor: '#1e1e30' },
  levelBadge:      {
    borderRadius: 8, paddingVertical: 4,
    paddingHorizontal: 8, minWidth: 54, alignItems: 'center',
  },
  levelText:       { fontSize: 11, fontWeight: '700' },
  compareDetails:  { flex: 1 },
  compareUseCase:  { fontSize: 12, color: '#ccc', fontWeight: '500', marginBottom: 3 },
  compareMetrics:  { flexDirection: 'row', gap: 12 },
  compareMetric:   { fontSize: 11, color: '#555' },

  explainCard:     {
    backgroundColor: '#13131f', borderRadius: 12,
    padding: 16, borderWidth: 0.5,
    borderColor: '#1e1e30', gap: 14,
  },
  explainRow:      { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  explainBadge:    {
    borderRadius: 8, paddingVertical: 3,
    paddingHorizontal: 8, minWidth: 52, alignItems: 'center',
  },
  explainLevel:    { fontSize: 11, fontWeight: '700' },
  explainDesc:     { fontSize: 12, color: '#888', flex: 1, lineHeight: 18 },
});