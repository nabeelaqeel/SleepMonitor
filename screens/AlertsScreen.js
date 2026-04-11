import React, { useState } from 'react';
import {
  View, Text, StyleSheet,
  FlatList, SafeAreaView, TouchableOpacity,
} from 'react-native';
import { useSleep } from '../context/SleepContext';

const TIER_STYLE = {
  Critical:   { border: '#ef4444', badge: '#3d1010', badgeText: '#f87171' },
  Important:  { border: '#f59e0b', badge: '#2d1f07', badgeText: '#fbbf24' },
  Normal:     { border: '#22c55e', badge: '#0a2010', badgeText: '#4ade80' },
  Background: { border: '#6b7280', badge: '#1a1a1a', badgeText: '#9ca3af' },
};

const FILTERS = ['All', 'Critical', 'Important'];

export default function AlertsScreen() {
  const { eventLog, sessionStats } = useSleep();
  const [filter, setFilter] = useState('All');

  const filtered = filter === 'All'
    ? eventLog
    : eventLog.filter(e => e.tier === filter);

  return (
    <SafeAreaView style={styles.container}>

      <View style={styles.header}>
        <Text style={styles.title}>Tonight's events</Text>
        <Text style={styles.subtitle}>
          {sessionStats.critical} critical · {sessionStats.important} important
        </Text>
      </View>

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

      <FlatList
        data={filtered}
        keyExtractor={item => item.id}
        contentContainerStyle={styles.list}
        showsVerticalScrollIndicator={false}
        renderItem={({ item }) => <EventItem event={item} />}
        ListEmptyComponent={
          <View style={styles.emptyWrap}>
            <Text style={styles.empty}>
              {eventLog.length === 0
                ? 'Waiting for data from classifier...'
                : 'No events for this filter.'}
            </Text>
          </View>
        }
      />

    </SafeAreaView>
  );
}

function EventItem({ event }) {
  const style = TIER_STYLE[event.tier];
  return (
    <View style={[styles.card, { borderLeftColor: style.border }]}>
      <View style={styles.cardTop}>
        <Text style={styles.cardTime}>{event.time}</Text>
        <View style={[styles.badge, { backgroundColor: style.badge }]}>
          <Text style={[styles.badgeText, { color: style.badgeText }]}>
            {event.tier}
          </Text>
        </View>
      </View>
      <View style={styles.cardValues}>
        <Text style={styles.valueText}>SpO2 {event.spo2}%</Text>
        <Text style={styles.valueSep}>·</Text>
        <Text style={styles.valueText}>HR {event.hr} bpm</Text>
      </View>
      <Text style={styles.reason}>{event.reason}</Text>
      <Text style={styles.topic}>{event.topic}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container:      { flex: 1, backgroundColor: '#0a0a0f' },
  header:         { paddingHorizontal: 20, paddingTop: 20, paddingBottom: 12 },
  title:          { fontSize: 26, fontWeight: '700', color: '#fff', marginBottom: 4 },
  subtitle:       { fontSize: 13, color: '#555' },
  filterRow:      { flexDirection: 'row', paddingHorizontal: 20, gap: 8, marginBottom: 14 },
  pill:           {
    paddingVertical: 6, paddingHorizontal: 14,
    borderRadius: 20, borderWidth: 0.5,
    borderColor: '#1e1e30', backgroundColor: '#13131f',
  },
  pillActive:     { backgroundColor: '#1a1a3a', borderColor: '#534AB7' },
  pillText:       { fontSize: 12, color: '#555', fontWeight: '500' },
  pillTextActive: { color: '#818cf8' },
  list:           { paddingHorizontal: 20, paddingBottom: 40 },
  card:           {
    backgroundColor: '#13131f', borderRadius: 12,
    padding: 14, marginBottom: 10,
    borderLeftWidth: 2.5, borderWidth: 0.5, borderColor: '#1e1e30',
  },
  cardTop:        {
    flexDirection: 'row', justifyContent: 'space-between',
    alignItems: 'center', marginBottom: 8,
  },
  cardTime:       { fontSize: 12, color: '#888', fontWeight: '500' },
  badge:          { borderRadius: 12, paddingVertical: 3, paddingHorizontal: 9 },
  badgeText:      { fontSize: 10, fontWeight: '700' },
  cardValues:     { flexDirection: 'row', alignItems: 'center', gap: 5, marginBottom: 4 },
  valueText:      { fontSize: 13, color: '#e5e5e5', fontWeight: '500' },
  valueSep:       { fontSize: 13, color: '#444' },
  reason:         { fontSize: 11, color: '#555', marginBottom: 4, fontStyle: 'italic' },
  topic:          { fontSize: 10, color: '#333', fontFamily: 'monospace' },
  emptyWrap:      { alignItems: 'center', marginTop: 60 },
  empty:          { color: '#444', fontSize: 13, textAlign: 'center' },
});