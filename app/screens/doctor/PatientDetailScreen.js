import { useState } from 'react';
import { View, Text, ScrollView, TouchableOpacity, ActivityIndicator, StyleSheet } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import VitalCard from '../../components/VitalCard';
import { useSleep, PATIENT_LIVE_WINDOW_MS } from '../../context/SleepContext';
import { useNow } from '../../hooks/useNow';
import { exportSessionReport } from '../../services/exportSessionReport';

const TIER_CONFIG = {
  Critical:   { bg: '#3d1010', text: '#f87171', border: '#7f1d1d',
                label: 'CRITICAL — apnea suspected', dot: '#ef4444' },
  Important:  { bg: '#2d1f07', text: '#fbbf24', border: '#78350f',
                label: 'IMPORTANT — abnormal trend', dot: '#f59e0b' },
  Normal:     { bg: '#0a2010', text: '#4ade80', border: '#14532d',
                label: 'NORMAL — routine sleep',    dot: '#22c55e' },
};

const HISTORY_TYPE_CONFIG = {
  Diagnosis:    { bg: '#1a1a3a', border: '#2a2a5a', text: '#818cf8' },
  Medication:   { bg: '#2d1f07', border: '#78350f', text: '#fbbf24' },
  'Lab Result': { bg: '#0a2010', border: '#14532d', text: '#4ade80' },
};

function deriveTier(spo2) {
  if (spo2 < 90) return 'Critical';
  if (spo2 < 95) return 'Important';
  return 'Normal';
}

function computeBmi(weight, height) {
  const h = height / 100;
  return (weight / (h * h)).toFixed(1);
}

function bmiColor(bmi) {
  const b = parseFloat(bmi);
  if (b < 18.5) return '#fbbf24';
  if (b < 25)   return '#4ade80';
  if (b < 30)   return '#fbbf24';
  return '#f87171';
}

function MedicalHistoryItem({ record }) {
  const cfg = HISTORY_TYPE_CONFIG[record.type] || HISTORY_TYPE_CONFIG.Diagnosis;
  return (
    <View style={histStyles.item}>
      <View style={histStyles.topRow}>
        <Text style={histStyles.date}>{record.date}</Text>
        <View style={[histStyles.typeBadge, { backgroundColor: cfg.bg, borderColor: cfg.border }]}>
          <Text style={[histStyles.typeText, { color: cfg.text }]}>{record.type}</Text>
        </View>
      </View>
      <Text style={histStyles.note}>{record.note}</Text>
      <Text style={histStyles.doctor}>{record.doctor}</Text>
    </View>
  );
}

export default function PatientDetailScreen({ route }) {
  const { patient } = route.params;
  const { patientSnapshots, sessionStats, currentData, sleepTimeline } = useSleep();
  const [exporting, setExporting] = useState(false);
  const now = useNow();

  // Live overlay: only the patient whose patientId is streaming gets fresh
  // values; everyone else shows the seeded record.
  const snapshot = patient.patientId ? patientSnapshots[patient.patientId] : null;
  const isLive   = !!snapshot && (now - snapshot.lastSeen) < PATIENT_LIVE_WINDOW_MS;

  const spo2 = isLive && snapshot.spo2 != null ? Math.round(snapshot.spo2) : patient.lastSpo2;
  const hr   = isLive && snapshot.heartRate != null ? Math.round(snapshot.heartRate) : patient.lastHr;
  const criticalCount = isLive ? sessionStats.critical : patient.criticalEvents;

  const tierKey  = isLive && TIER_CONFIG[snapshot.tier] ? snapshot.tier : deriveTier(spo2);
  const tier     = TIER_CONFIG[tierKey];

  const spo2Color = spo2 < 90 ? '#f87171'
                  : spo2 < 95 ? '#fbbf24' : '#4ade80';
  const hrColor   = hr < 40 || hr > 100 ? '#f87171' : '#4ade80';
  const bmi       = computeBmi(patient.weight, patient.height);

  // The PDF export reuses the patient-side report (services/exportSessionReport).
  // It can only cover this patient if they have streamed during this app run,
  // so the button stays disabled for records that never had a session.
  const canExport = !!snapshot;

  async function handleExportReport() {
    setExporting(true);
    try {
      await exportSessionReport({
        sessionStats,
        currentData,
        sleepTimeline,
        patientName: patient.name,
        patientId: patient.patientId,
      });
    } catch (e) {
      console.error('PDF export failed:', e);
    } finally {
      setExporting(false);
    }
  }

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={styles.scroll}
      showsVerticalScrollIndicator={false}
    >
      {/* Patient identity */}
      <View style={styles.identityRow}>
        <View style={styles.avatarWrap}>
          <MaterialCommunityIcons name="account" size={28} color="#818cf8" />
        </View>
        <View>
          <Text style={styles.patientName}>{patient.name}</Text>
          <Text style={styles.patientMeta}>Age {patient.age} · ID #{patient.id}{patient.patientId ? ` · ${patient.patientId}` : ''}</Text>
        </View>
      </View>

      {/* Tier status card — mirrors HomeScreen */}
      <View style={[styles.tierCard, { backgroundColor: tier.bg, borderColor: tier.border }]}>
        <View style={styles.tierLeft}>
          <View style={[styles.tierDot, { backgroundColor: tier.dot }]} />
          <Text style={[styles.tierLabel, { color: tier.text }]}>{tier.label}</Text>
        </View>
      </View>

      {/* Vitals grid */}
      <Text style={styles.sectionLabel}>{isLive ? 'Live readings' : 'Last recorded readings'}</Text>
      <View style={styles.grid}>
        <VitalCard
          label="SpO2"
          value={`${spo2}%`}
          color={spo2Color}
        />
        <VitalCard
          label="Heart Rate"
          value={`${hr} bpm`}
          color={hrColor}
        />
        <VitalCard
          label="Critical Events"
          value={`${criticalCount}`}
          color={criticalCount > 0 ? '#f87171' : '#4ade80'}
        />
        <VitalCard
          label="Status"
          value={isLive ? 'Live now' : patient.status.charAt(0).toUpperCase() + patient.status.slice(1)}
          color={isLive ? '#4ade80' : '#9ca3af'}
        />
      </View>

      {/* Physical metrics */}
      <Text style={styles.sectionLabel}>Physical metrics</Text>
      <View style={styles.grid}>
        <VitalCard label="Age"    value={`${patient.age} yrs`}   color="#9ca3af" />
        <VitalCard label="Weight" value={`${patient.weight} kg`}  color="#9ca3af" />
        <VitalCard label="Height" value={`${patient.height} cm`}  color="#9ca3af" />
        <VitalCard label="BMI"    value={bmi}                     color={bmiColor(bmi)} />
      </View>

      {/* Medical history */}
      <Text style={styles.sectionLabel}>Medical history</Text>
      <View style={{ marginBottom: 22 }}>
        {(patient.medicalHistory || []).map(r => (
          <MedicalHistoryItem key={r.id} record={r} />
        ))}
      </View>

      {/* Critical events callout */}
      {criticalCount > 0 && (
        <View style={styles.alertBox}>
          <MaterialCommunityIcons name="alert-circle" size={16} color="#f87171" />
          <View style={{ flex: 1 }}>
            <Text style={styles.alertTitle}>
              {criticalCount} critical event{criticalCount > 1 ? 's' : ''} recorded
            </Text>
            <Text style={styles.alertBody}>
              SpO2 dropped below threshold during this session. Review MQTT alert log for timestamps.
            </Text>
          </View>
        </View>
      )}

      {/* Session report export */}
      <TouchableOpacity
        style={[styles.exportBtn, (!canExport || exporting) && styles.exportBtnDisabled]}
        onPress={handleExportReport}
        disabled={!canExport || exporting}
        activeOpacity={0.75}
      >
        {exporting
          ? <ActivityIndicator size="small" color="#818cf8" />
          : <MaterialCommunityIcons name="file-pdf-box" size={18} color={canExport ? '#818cf8' : '#444'} />
        }
        <Text style={[styles.exportText, !canExport && { color: '#444' }]}>
          {exporting
            ? 'Exporting...'
            : canExport
              ? (isLive ? 'Export PDF' : 'Export PDF (last session)')
              : 'No session to export'}
        </Text>
      </TouchableOpacity>

      {/* MQTT topic row */}
      <View style={styles.mqttRow}>
        <Text style={styles.mqttLabel}>MQTT topic</Text>
        <Text style={styles.mqttTopic}>{isLive && snapshot.topic ? snapshot.topic : 'no live session'}</Text>
      </View>

      {/* Live / static notice */}
      <View style={styles.phaseNotice}>
        <MaterialCommunityIcons
          name={isLive ? 'access-point' : 'information-outline'}
          size={14}
          color={isLive ? '#4ade80' : '#444'}
        />
        <Text style={[styles.phaseText, isLive && { color: '#4ade80' }]}>
          {isLive
            ? 'Streaming live from the MQTT broker'
            : patient.patientId
              ? 'No live session — showing the last recorded readings'
              : 'Static demo record — no device assigned'}
        </Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root:   { flex: 1, backgroundColor: '#0a0a0f' },
  scroll: { padding: 20, paddingBottom: 48 },

  // Identity
  identityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    marginBottom: 20,
  },
  avatarWrap: {
    width: 52,
    height: 52,
    borderRadius: 16,
    backgroundColor: '#13132a',
    borderWidth: 1,
    borderColor: '#2a2a4a',
    alignItems: 'center',
    justifyContent: 'center',
  },
  patientName: {
    fontSize: 20,
    fontWeight: '700',
    color: '#e2e8f0',
  },
  patientMeta: {
    fontSize: 12,
    color: '#555',
    marginTop: 3,
  },

  // Tier card — same structure as HomeScreen
  tierCard: {
    borderRadius: 14,
    borderWidth: 1,
    padding: 14,
    marginBottom: 22,
  },
  tierLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  tierDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  tierLabel: {
    fontSize: 13,
    fontWeight: '700',
  },

  // Grid
  sectionLabel: {
    fontSize: 11,
    color: '#555',
    marginBottom: 10,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
    marginBottom: 22,
  },

  // Alert box
  alertBox: {
    flexDirection: 'row',
    gap: 10,
    backgroundColor: '#1a0a0a',
    borderRadius: 12,
    padding: 14,
    borderWidth: 1,
    borderColor: '#7f1d1d',
    marginBottom: 16,
    alignItems: 'flex-start',
  },
  alertTitle: {
    fontSize: 13,
    color: '#f87171',
    fontWeight: '700',
    marginBottom: 4,
  },
  alertBody: {
    fontSize: 12,
    color: '#888',
    lineHeight: 18,
  },

  // Report export
  exportBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#13131f',
    borderWidth: 1,
    borderColor: '#2a2a4a',
    borderRadius: 10,
    paddingVertical: 12,
    marginBottom: 16,
  },
  exportBtnDisabled: {
    opacity: 0.5,
  },
  exportText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#818cf8',
  },

  // MQTT row
  mqttRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: '#13131f',
    borderRadius: 10,
    padding: 12,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    marginBottom: 24,
  },
  mqttLabel: { fontSize: 12, color: '#555' },
  mqttTopic: { fontSize: 12, color: '#818cf8', fontWeight: '600' },

  // Phase 2 notice
  phaseNotice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    justifyContent: 'center',
  },
  phaseText: {
    fontSize: 12,
    color: '#444',
    fontStyle: 'italic',
  },
});

const histStyles = StyleSheet.create({
  item: {
    backgroundColor: '#0d0d18',
    borderRadius: 12,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    padding: 14,
    marginBottom: 10,
  },
  topRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  date: {
    fontSize: 12,
    color: '#555',
  },
  typeBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    borderWidth: 1,
  },
  typeText: {
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 0.3,
  },
  note: {
    fontSize: 13,
    color: '#c4c4d4',
    lineHeight: 19,
    marginBottom: 6,
  },
  doctor: {
    fontSize: 11,
    color: '#444',
  },
});
