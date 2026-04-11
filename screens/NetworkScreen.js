import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  SafeAreaView,
  TouchableOpacity,
} from 'react-native';

const MOCK_NETWORK = {
  brokerAddress: 'localhost:1883',
  connected: true,
  totalMessages: 1847,
  topics: [
    {
      name: 'sleep/critical',
      qos: 2,
      qosLabel: 'QoS 2 — guaranteed',
      messages: 3,
      deliveryRate: 100,
      latency: 12,
      color: '#f87171',
      badgeBg: '#3d1010',
    },
    {
      name: 'sleep/important',
      qos: 1,
      qosLabel: 'QoS 1 — at least once',
      messages: 2,
      deliveryRate: 98,
      latency: 28,
      color: '#fbbf24',
      badgeBg: '#2d1f07',
    },
    {
      name: 'sleep/normal',
      qos: 0,
      qosLabel: 'QoS 0 — best effort',
      messages: 1390,
      deliveryRate: 91,
      latency: 45,
      color: '#4ade80',
      badgeBg: '#0a2010',
    },
    {
      name: 'sleep/background',
      qos: 0,
      qosLabel: 'QoS 0 — batch',
      messages: 452,
      deliveryRate: 84,
      latency: 120,
      color: '#9ca3af',
      badgeBg: '#1a1a1a',
    },
  ],
};

export default function NetworkScreen() {
  const [connected, setConnected] = useState(MOCK_NETWORK.connected);
  const net = MOCK_NETWORK;

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        {/* Header */}
        <Text style={styles.title}>QoS network status</Text>
        <Text style={styles.subtitle}>MQTT broker monitoring</Text>

        {/* Broker status card */}
        <View style={styles.brokerCard}>
          <View style={styles.brokerRow}>
            <View>
              <Text style={styles.brokerLabel}>Broker address</Text>
              <Text style={styles.brokerAddress}>{net.brokerAddress}</Text>
            </View>
            <View style={[
              styles.statusBadge,
              { backgroundColor: connected ? '#0a2010' : '#3d1010' }
            ]}>
              <View style={[
                styles.statusDot,
                { backgroundColor: connected ? '#22c55e' : '#ef4444' }
              ]} />
              <Text style={[
                styles.statusText,
                { color: connected ? '#4ade80' : '#f87171' }
              ]}>
                {connected ? 'Connected' : 'Disconnected'}
              </Text>
            </View>
          </View>

          <View style={styles.divider} />

          <View style={styles.brokerStats}>
            <View style={styles.statItem}>
              <Text style={styles.statValue}>{net.totalMessages.toLocaleString()}</Text>
              <Text style={styles.statLabel}>Total messages</Text>
            </View>
            <View style={styles.statItem}>
              <Text style={styles.statValue}>4</Text>
              <Text style={styles.statLabel}>Active topics</Text>
            </View>
            <View style={styles.statItem}>
              <Text style={styles.statValue}>12 ms</Text>
              <Text style={styles.statLabel}>Critical latency</Text>
            </View>
          </View>
        </View>

        {/* Topic cards */}
        <Text style={styles.sectionLabel}>Topic delivery rates</Text>
        {net.topics.map(topic => (
          <TopicCard key={topic.name} topic={topic} />
        ))}

        {/* QoS explanation */}
        <Text style={styles.sectionLabel}>QoS levels explained</Text>
        <View style={styles.explainCard}>
          <ExplainRow
            level="QoS 2"
            color="#f87171"
            desc="Exactly once — guaranteed delivery. Used for Critical events."
          />
          <ExplainRow
            level="QoS 1"
            color="#fbbf24"
            desc="At least once — may duplicate. Used for Important trends."
          />
          <ExplainRow
            level="QoS 0"
            color="#9ca3af"
            desc="Best effort — may be lost. Used for Normal and Background data."
          />
        </View>

        {/* Simulate button */}
        <TouchableOpacity
          style={styles.simButton}
          onPress={() => setConnected(prev => !prev)}
        >
          <Text style={styles.simButtonText}>
            Simulate {connected ? 'disconnect' : 'connect'}
          </Text>
        </TouchableOpacity>

      </ScrollView>
    </SafeAreaView>
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
        <TopicStat label="Messages"     value={topic.messages.toLocaleString()} />
        <TopicStat label="Delivery"     value={`${topic.deliveryRate}%`}        />
        <TopicStat label="Avg latency"  value={`${topic.latency} ms`}           />
      </View>

      {/* Delivery rate bar */}
      <View style={styles.deliveryTrack}>
        <View style={[styles.deliveryFill, {
          width: `${topic.deliveryRate}%`,
          backgroundColor: topic.color,
        }]} />
      </View>
    </View>
  );
}

function TopicStat({ label, value }) {
  return (
    <View style={styles.topicStatItem}>
      <Text style={styles.topicStatValue}>{value}</Text>
      <Text style={styles.topicStatLabel}>{label}</Text>
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
    backgroundColor: '#13131f',
    borderRadius: 14,
    padding: 16,
    marginBottom: 24,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
  },
  brokerRow:       {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  brokerLabel:     { fontSize: 11, color: '#555', marginBottom: 4 },
  brokerAddress:   { fontSize: 14, color: '#e5e5e5', fontFamily: 'monospace' },
  statusBadge:     {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 20,
  },
  statusDot:       { width: 7, height: 7, borderRadius: 4 },
  statusText:      { fontSize: 12, fontWeight: '600' },
  divider:         { height: 0.5, backgroundColor: '#1e1e30', marginVertical: 14 },
  brokerStats:     { flexDirection: 'row', justifyContent: 'space-around' },
  statItem:        { alignItems: 'center' },
  statValue:       { fontSize: 18, fontWeight: '700', color: '#fff', marginBottom: 2 },
  statLabel:       { fontSize: 10, color: '#555' },

  topicCard:       {
    backgroundColor: '#13131f',
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    borderLeftWidth: 2.5,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
  },
  topicTop:        {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
    flexWrap: 'wrap',
    gap: 6,
  },
  topicName:       { fontSize: 13, color: '#e5e5e5', fontFamily: 'monospace', fontWeight: '600' },
  qosBadge:        { borderRadius: 10, paddingVertical: 3, paddingHorizontal: 8 },
  qosBadgeText:    { fontSize: 10, fontWeight: '600' },
  topicStats:      { flexDirection: 'row', gap: 20, marginBottom: 10 },
  topicStatItem:   {},
  topicStatValue:  { fontSize: 15, fontWeight: '700', color: '#fff' },
  topicStatLabel:  { fontSize: 10, color: '#555', marginTop: 2 },
  deliveryTrack:   {
    height: 4,
    backgroundColor: '#1a1a2e',
    borderRadius: 2,
    overflow: 'hidden',
  },
  deliveryFill:    { height: '100%', borderRadius: 2 },

  explainCard:     {
    backgroundColor: '#13131f',
    borderRadius: 12,
    padding: 16,
    marginBottom: 20,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    gap: 14,
  },
  explainRow:      { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  explainBadge:    {
    borderRadius: 8,
    paddingVertical: 3,
    paddingHorizontal: 8,
    minWidth: 52,
    alignItems: 'center',
  },
  explainLevel:    { fontSize: 11, fontWeight: '700' },
  explainDesc:     { fontSize: 12, color: '#888', flex: 1, lineHeight: 18 },

  simButton:       {
    backgroundColor: '#13131f',
    borderRadius: 12,
    padding: 14,
    alignItems: 'center',
    borderWidth: 0.5,
    borderColor: '#1e1e30',
  },
  simButtonText:   { fontSize: 13, color: '#818cf8', fontWeight: '600' },
});