import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, SafeAreaView
} from 'react-native';

// Mock data — replace with real MQTT data later
const MOCK_DATA = {
  spo2: 87,
  heartRate: 52,
  hrv: 18,
  motion: 'Low',
  tier: 'Critical',
  timestamp: '02:14 AM',
};

const TIER_COLORS = {
  Critical:   { bg: '#3d1010', text: '#f87171', border: '#7f1d1d' },
  Important:  { bg: '#2d1f07', text: '#fbbf24', border: '#78350f' },
  Normal:     { bg: '#0a2010', text: '#4ade80', border: '#14532d' },
  Background: { bg: '#1a1a1a', text: '#9ca3af', border: '#374151' },
};

export default function HomeScreen() {
  const [data, setData] = useState(MOCK_DATA);
  const tier = TIER_COLORS[data.tier];

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll}>

        <Text style={styles.title}>Sleep monitor</Text>

        {/* Tier badge */}
        <View style={[styles.tierBadge, { backgroundColor: tier.bg, borderColor: tier.border }]}>
          <Text style={[styles.tierText, { color: tier.text }]}>
            {data.tier.toUpperCase()} — apnea suspected
          </Text>
        </View>

        {/* Vital cards grid */}
        <View style={styles.grid}>
          <VitalCard label="SpO2"        value={`${data.spo2}%`}        color="#f87171" />
          <VitalCard label="Heart rate"  value={`${data.heartRate} bpm`} color="#f87171" />
          <VitalCard label="HRV (RMSSD)" value={`${data.hrv} ms`}       color="#fbbf24" />
          <VitalCard label="Motion"      value={data.motion}             color="#4ade80" />
        </View>

        {/* Alert box */}
        {data.tier === 'Critical' && (
          <View style={styles.alertBox}>
            <Text style={styles.alertTitle}>Alert — SpO2 below 90%</Text>
            <Text style={styles.alertSub}>{data.timestamp} — QoS 2 transmitted</Text>
          </View>
        )}

      </ScrollView>
    </SafeAreaView>
  );
}

function VitalCard({ label, value, color }) {
  return (
    <View style={styles.vitalCard}>
      <Text style={styles.vitalLabel}>{label}</Text>
      <Text style={[styles.vitalValue, { color }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container:   { flex: 1, backgroundColor: '#0a0a0f' },
  scroll:      { padding: 20 },
  title:       { fontSize: 22, fontWeight: '600', color: '#fff', marginBottom: 14 },
  tierBadge:   { borderRadius: 20, borderWidth: 1, paddingVertical: 6,
                 paddingHorizontal: 14, alignSelf: 'flex-start', marginBottom: 16 },
  tierText:    { fontSize: 12, fontWeight: '700' },
  grid:        { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 16 },
  vitalCard:   { width: '47%', backgroundColor: '#13131f', borderRadius: 10,
                 padding: 12, borderWidth: 0.5, borderColor: '#1e1e30' },
  vitalLabel:  { fontSize: 11, color: '#666', marginBottom: 4 },
  vitalValue:  { fontSize: 22, fontWeight: '700', color: '#fff' },
  alertBox:    { backgroundColor: '#1a0a0a', borderRadius: 10, padding: 12,
                 borderWidth: 1, borderColor: '#7f1d1d' },
  alertTitle:  { fontSize: 12, color: '#f87171', fontWeight: '700' },
  alertSub:    { fontSize: 11, color: '#888', marginTop: 3 },
});