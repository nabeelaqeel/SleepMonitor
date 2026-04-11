import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  SafeAreaView,
  TouchableOpacity,
} from 'react-native';

// Mock event log — replace with real MQTT message history later
const MOCK_EVENTS = [
  { id: '1', tier: 'Critical',   time: '02:14 AM', spo2: 87, hr: 52, duration: '2m 10s', topic: 'sleep/critical'   },
  { id: '2', tier: 'Important',  time: '02:08 AM', spo2: 91, hr: 58, duration: '45s',    topic: 'sleep/important'  },
  { id: '3', tier: 'Critical',   time: '00:47 AM', spo2: 89, hr: 49, duration: '1m 30s', topic: 'sleep/critical'   },
  { id: '4', tier: 'Important',  time: '00:31 AM', spo2: 92, hr: 61, duration: '30s',    topic: 'sleep/important'  },
  { id: '5', tier: 'Critical',   time: '11:58 PM', spo2: 88, hr: 50, duration: '1m 05s', topic: 'sleep/critical'   },
  { id: '6', tier: 'Normal',     time: '11:32 PM', spo2: 96, hr: 56, duration: '—',      topic: 'sleep/normal'     },
  { id: '7', tier: 'Normal',     time: '11:20 PM', spo2: 97, hr: 55, duration: '—',      topic: 'sleep/normal'     },
  { id: '8', tier: 'Background', time: '11:00 PM', spo2: 98, hr: 54, duration: '—',      topic: 'sleep/background' },
];

const TIER_STYLE = {
  Critical:   { border: '#ef4444', badge: '#3d1010', badgeText: '#f87171' },
  Important:  { border: '#f59e0b', badge: '#2d1f07', badgeText: '#fbbf24' },
  Normal:     { border: '#22c55e', badge: '#0a2010', badgeText: '#4ade80' },
  Background: { border: '#6b7280', badge: '#1a1a1a', badgeText: '#9ca3af' },
};

const FILTERS = ['All', 'Critical', 'Important', 'Normal'];

export default function AlertsScreen() {
  const [filter, setFilter] = useState('All');

  const filtered = filter === 'All'
    ? MOCK_EVENTS
    : MOCK_EVENTS.filter(e => e.tier === filter);

  // Summary counts
  const criticalCount  = MOCK_EVENTS.filter(e => e.tier === 'Critical').length;
  const importantCount = MOCK_EVENTS.filter(e => e.tier === 'Important').length;

  return (
    <SafeAreaView style={styles.container}>

      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.title}>Tonight's events</Text>
        <Text style={styles.subtitle}>
          {criticalCount} critical · {importantCount} important
        </Text>
      </View>

      {/* Filter pills */}
      <View style={styles.filterRow}>
        {FILTERS.map(f => (
          <TouchableOpacity
            key={f}
            style={[styles.pill, filter === f && styles.pillActive]}
            onPress={() => setFilter(f)}
          >
            <Text style={[styles.pillText, filter === f && styles.pillTextActive]}>
              {f}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Event list */}
      <FlatList
        data={filtered}
        keyExtractor={item => item.id}
        contentContainerStyle={styles.list}
        showsVerticalScrollIndicator={false}
        renderItem={({ item }) => <EventItem event={item} />}
        ListEmptyComponent={
          <Text style={styles.empty}>No events for this filter.</Text>
        }
      />

    </SafeAreaView>
  );
}

function EventItem({ event }) {
  const style = TIER_STYLE[event.tier];

  return (
    <View style={[styles.card, { borderLeftColor: style.border }]}>

      {/* Top row */}
      <View style={styles.cardTop}>
        <Text style={styles.cardTime}>{event.time}</Text>
        <View style={[styles.badge, { backgroundColor: style.badge }]}>
          <Text style={[styles.badgeText, { color: style.badgeText }]}>
            {event.tier}
          </Text>
        </View>
      </View>

      {/* Values row */}
      <View style={styles.cardValues}>
        <Text style={styles.valueText}>SpO2 {event.spo2}%</Text>
        <Text style={styles.valueSep}>·</Text>
        <Text style={styles.valueText}>HR {event.hr} bpm</Text>
        {event.duration !== '—' && (
          <>
            <Text style={styles.valueSep}>·</Text>
            <Text style={styles.valueText}>{event.duration}</Text>
          </>
        )}
      </View>

      {/* MQTT topic */}
      <Text style={styles.topic}>{event.topic}</Text>

    </View>
  );
}

const styles = StyleSheet.create({
  container:      { flex: 1, backgroundColor: '#0a0a0f' },

  header:         { paddingHorizontal: 20, paddingTop: 20, paddingBottom: 12 },
  title:          { fontSize: 26, fontWeight: '700', color: '#fff', marginBottom: 4 },
  subtitle:       { fontSize: 13, color: '#555' },

  filterRow:      {
    flexDirection: 'row',
    paddingHorizontal: 20,
    gap: 8,
    marginBottom: 14,
  },
  pill:           {
    paddingVertical: 6,
    paddingHorizontal: 14,
    borderRadius: 20,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    backgroundColor: '#13131f',
  },
  pillActive:     { backgroundColor: '#1a1a3a', borderColor: '#534AB7' },
  pillText:       { fontSize: 12, color: '#555', fontWeight: '500' },
  pillTextActive: { color: '#818cf8' },

  list:           { paddingHorizontal: 20, paddingBottom: 40 },

  card:           {
    backgroundColor: '#13131f',
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    borderLeftWidth: 2.5,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
  },
  cardTop:        {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  cardTime:       { fontSize: 12, color: '#888', fontWeight: '500' },
  badge:          { borderRadius: 12, paddingVertical: 3, paddingHorizontal: 9 },
  badgeText:      { fontSize: 10, fontWeight: '700' },

  cardValues:     { flexDirection: 'row', alignItems: 'center', gap: 5, marginBottom: 6 },
  valueText:      { fontSize: 13, color: '#e5e5e5', fontWeight: '500' },
  valueSep:       { fontSize: 13, color: '#444' },

  topic:          { fontSize: 10, color: '#444', fontFamily: 'monospace' },

  empty:          { textAlign: 'center', color: '#555', marginTop: 40, fontSize: 13 },
});