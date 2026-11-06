import { useState } from 'react';
import {
  View, Text, StyleSheet,
  FlatList, TouchableOpacity,
} from 'react-native';
import { tierShortLabel, topicDisplayLabel } from '../config/displayText';

const TIER_STYLE = {
  Critical:   { border: '#ef4444', badge: '#3d1010', badgeText: '#f87171' },
  Important:  { border: '#f59e0b', badge: '#2d1f07', badgeText: '#fbbf24' },
  Normal:     { border: '#22c55e', badge: '#0a2010', badgeText: '#4ade80' },
  Background: { border: '#6b7280', badge: '#1a1a1a', badgeText: '#9ca3af' },
};

// Filter pills display the centralized short labels, but filtering still
// compares raw code identifiers ('Critical' / 'Important') — never renamed.
const FILTERS = ['All', 'Critical', 'Important'];

// Shared event log — used by the patient's Alerts tab and the doctor's
// Alerts tab. `emptyMessage` is shown when no events have arrived at all;
// the "nothing matches the current filter" case is handled internally.
//
// `patientLabel` is reserved for genuinely multi-patient streams (per-patient
// topics). When provided, every card shows a chip naming the patient.
export default function EventLog({
  events,
  emptyMessage = 'Waiting for data from classifier...',
  patientLabel,
}) {
  const [filter, setFilter] = useState('All');

  const filtered = filter === 'All'
    ? events
    : events.filter(e => e.tier === filter);

  return (
    <View style={styles.root}>
      <View style={styles.filterRow}>
        {FILTERS.map(f => (
          <TouchableOpacity
            key={f}
            style={[styles.pill, filter === f && styles.pillActive]}
            onPress={() => setFilter(f)}
          >
            <Text style={[styles.pillText, filter === f && styles.pillTextActive]}>
              {f === 'All' ? f : tierShortLabel(f)}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <FlatList
        data={filtered}
        keyExtractor={item => item.id}
        contentContainerStyle={styles.list}
        showsVerticalScrollIndicator={false}
        renderItem={({ item }) => <EventItem event={item} patientLabel={patientLabel} />}
        ListEmptyComponent={
          <View style={styles.emptyWrap}>
            <Text style={styles.empty}>
              {events.length === 0
                ? emptyMessage
                : 'No events for this filter.'}
            </Text>
          </View>
        }
      />
    </View>
  );
}

function EventItem({ event, patientLabel }) {
  const style = TIER_STYLE[event.tier];
  return (
    <View style={[styles.card, { borderLeftColor: style.border }]}>
      <View style={styles.cardTop}>
        <Text style={styles.cardTime}>{event.time}</Text>
        <View style={styles.cardTopRight}>
          {patientLabel ? (
            <Text style={styles.patientChip}>{patientLabel}</Text>
          ) : null}
          <View style={[styles.badge, { backgroundColor: style.badge }]}>
            <Text style={[styles.badgeText, { color: style.badgeText }]}>
              {tierShortLabel(event.tier)}
            </Text>
          </View>
        </View>
      </View>
      <View style={styles.cardValues}>
        <Text style={styles.valueText}>SpO2 {event.spo2}%</Text>
        <Text style={styles.valueSep}>·</Text>
        <Text style={styles.valueText}>HR {event.hr} bpm</Text>
      </View>
      <Text style={styles.reason}>{event.reason}</Text>
      <Text style={styles.topic}>{topicDisplayLabel(event.topic)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root:           { flex: 1 },
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
  cardTopRight:   { flexDirection: 'row', alignItems: 'center', gap: 6 },
  cardTime:       { fontSize: 12, color: '#888', fontWeight: '500' },
  patientChip:    {
    fontSize: 10, color: '#818cf8', backgroundColor: '#1a1a3a',
    borderRadius: 10, paddingVertical: 2, paddingHorizontal: 8,
    overflow: 'hidden',
  },
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
