import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  SafeAreaView,
} from 'react-native';
import VitalCard from '../components/VitalCard';
import { connectMQTT, disconnectMQTT } from '../services/mqttService';

const DEFAULT_DATA = {
  tier:        'Normal',
  spo2:        97,
  heartRate:   56,
  hrv:         35,
  motion:      'Low',
  timestamp:   '--:-- --',
  lastUpdated: 'Waiting for data...',
};

// ── Tier colour config ────────────────────────────────
const TIER_CONFIG = {
  Critical: {
    bg: '#3d1010',
    text: '#f87171',
    border: '#7f1d1d',
    label: 'CRITICAL — apnea suspected',
    dot: '#ef4444',
  },
  Important: {
    bg: '#2d1f07',
    text: '#fbbf24',
    border: '#78350f',
    label: 'IMPORTANT — abnormal trend',
    dot: '#f59e0b',
  },
  Normal: {
    bg: '#0a2010',
    text: '#4ade80',
    border: '#14532d',
    label: 'NORMAL — routine sleep',
    dot: '#22c55e',
  },
  Background: {
    bg: '#1a1a1a',
    text: '#9ca3af',
    border: '#374151',
    label: 'BACKGROUND — statistics',
    dot: '#6b7280',
  },
};

// ── SpO2 sparkline data (last 10 readings) ────────────
const SPARKLINE = [96, 96, 95, 94, 92, 89, 87, 87, 88, 87];

export default function HomeScreen() {
  const [data, setData]           = useState(DEFAULT_DATA);
  const [sparkline, setSparkline] = useState([97,97,97,97,97,97,97,97,97,97]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    connectMQTT((topic, incoming) => {
      setConnected(true);
      setData({
        tier:        incoming.tier,
        spo2:        incoming.spo2,
        heartRate:   incoming.heartRate,
        hrv:         incoming.hrv,
        motion:      'Low',
        timestamp:   incoming.timestamp,
        lastUpdated: 'Just now',
      });
      setSparkline(prev => {
        const updated = [...prev, incoming.spo2];
        return updated.slice(-10);
      });
    });

    return () => { disconnectMQTT(); };
  }, []);

  const tier      = TIER_CONFIG[data.tier] || TIER_CONFIG.Normal;
  const spo2Color = data.spo2 < 90 ? '#f87171' : data.spo2 < 95 ? '#fbbf24' : '#4ade80';
  const hrColor   = data.heartRate < 40 || data.heartRate > 100 ? '#f87171' : '#4ade80';
  const hrvColor  = data.hrv < 20 ? '#fbbf24' : '#4ade80';

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.appTitle}>Sleep monitor</Text>
          <View style={styles.liveRow}>
            <View style={[styles.liveDot, { backgroundColor: tier.dot }]} />
            <Text style={styles.liveText}>Live · {data.lastUpdated}</Text>
          </View>
        </View>

        {/* Tier status card */}
        <View style={[styles.tierCard, {
          backgroundColor: tier.bg,
          borderColor: tier.border,
        }]}>
          <Text style={[styles.tierLabel, { color: tier.text }]}>
            {tier.label}
          </Text>
          <Text style={[styles.tierTime, { color: tier.text }]}>
            {data.timestamp}
          </Text>
        </View>

        {/* Vitals grid */}
        <Text style={styles.sectionLabel}>Current readings</Text>
        <View style={styles.grid}>
          <VitalCard label="SpO2"         value={`${data.spo2}%`}           color={spo2Color} />
          <VitalCard label="Heart rate"   value={`${data.heartRate} bpm`}   color={hrColor}   />
          <VitalCard label="HRV (RMSSD)"  value={`${data.hrv} ms`}          color={hrvColor}  />
          <VitalCard label="Motion"       value={data.motion}                color="#9ca3af"   />
        </View>

        {/* SpO2 sparkline */}
        <Text style={styles.sectionLabel}>SpO2 trend — last 10 readings</Text>
        <View style={styles.sparkCard}>
          <SparkLine data={SPARKLINE} />
          <View style={styles.sparkLegend}>
            <Text style={styles.sparkMin}>Min: {Math.min(...SPARKLINE)}%</Text>
            <Text style={styles.sparkMax}>Max: {Math.max(...SPARKLINE)}%</Text>
          </View>
        </View>

        {/* Alert box — only shows when Critical */}
        {data.tier === 'Critical' && (
          <View style={styles.alertBox}>
            <Text style={styles.alertTitle}>Immediate alert sent</Text>
            <Text style={styles.alertBody}>
              SpO2 dropped to {data.spo2}% at {data.timestamp}.
              Transmitted via MQTT QoS 2 — guaranteed delivery.
            </Text>
          </View>
        )}

        {/* MQTT info footer */}
        <View style={styles.mqttRow}>
          <Text style={styles.mqttLabel}>MQTT topic</Text>
          <Text style={styles.mqttTopic}>
            sleep/{data.tier.toLowerCase()}
          </Text>
        </View>

      </ScrollView>
    </SafeAreaView>
  );
}

// ── Sparkline component ───────────────────────────────
function SparkLine({ data }) {
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;

  return (
    <View style={spark.container}>
      {data.map((val, i) => {
        const heightPct = ((val - min) / range) * 100;
        const barColor  = val < 90 ? '#ef4444' : val < 95 ? '#f59e0b' : '#4ade80';
        return (
          <View key={i} style={spark.barWrap}>
            <View
              style={[
                spark.bar,
                {
                  height: `${Math.max(heightPct, 10)}%`,
                  backgroundColor: barColor,
                },
              ]}
            />
          </View>
        );
      })}
    </View>
  );
}

// ── Styles ────────────────────────────────────────────
const styles = StyleSheet.create({
  container:    { flex: 1, backgroundColor: '#0a0a0f' },
  scroll:       { padding: 20, paddingBottom: 40 },

  header:       { marginBottom: 16 },
  appTitle:     { fontSize: 26, fontWeight: '700', color: '#ffffff', marginBottom: 4 },
  liveRow:      { flexDirection: 'row', alignItems: 'center', gap: 6 },
  liveDot:      { width: 7, height: 7, borderRadius: 4 },
  liveText:     { fontSize: 12, color: '#555' },

  tierCard:     {
    borderRadius: 14,
    borderWidth: 1,
    padding: 16,
    marginBottom: 22,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  tierLabel:    { fontSize: 13, fontWeight: '700', flex: 1 },
  tierTime:     { fontSize: 12, opacity: 0.7 },

  sectionLabel: { fontSize: 11, color: '#555', marginBottom: 10,
                  letterSpacing: 0.5, textTransform: 'uppercase' },

  grid:         { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 22 },

  sparkCard:    {
    backgroundColor: '#0d0d18',
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
  },
  sparkLegend:  { flexDirection: 'row', justifyContent: 'space-between', marginTop: 8 },
  sparkMin:     { fontSize: 11, color: '#f87171' },
  sparkMax:     { fontSize: 11, color: '#4ade80' },

  alertBox:     {
    backgroundColor: '#1a0a0a',
    borderRadius: 12,
    padding: 14,
    borderWidth: 1,
    borderColor: '#7f1d1d',
    marginBottom: 16,
  },
  alertTitle:   { fontSize: 13, color: '#f87171', fontWeight: '700', marginBottom: 4 },
  alertBody:    { fontSize: 12, color: '#888', lineHeight: 18 },

  mqttRow:      {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: '#13131f',
    borderRadius: 10,
    padding: 12,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
  },
  mqttLabel:    { fontSize: 12, color: '#555' },
  mqttTopic:    { fontSize: 12, color: '#818cf8', fontWeight: '600' },
});

const spark = StyleSheet.create({
  container:  {
    flexDirection: 'row',
    alignItems: 'flex-end',
    height: 52,
    gap: 4,
  },
  barWrap:    { flex: 1, height: '100%', justifyContent: 'flex-end' },
  bar:        { borderRadius: 3, minHeight: 4 },
});