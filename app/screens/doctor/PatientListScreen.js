import { View, Text, FlatList, TouchableOpacity, StyleSheet } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useSleep, PATIENT_LIVE_WINDOW_MS } from '../../context/SleepContext';
import { useNow } from '../../hooks/useNow';

const MOCK_PATIENTS = [
  {
    id: '2',
    name: 'Ali Hassan',
    patientId: 'patient-001',   // matches the publisher's PATIENT_ID — this row goes live
    age: 34,
    lastSpo2: 96,
    lastHr: 58,
    criticalEvents: 2,
    status: 'active',
    weight: 78,
    height: 175,
    medicalHistory: [
      { id: 'mh1', date: '2025-03-10', type: 'Diagnosis',   note: 'Mild obstructive sleep apnea (AHI 8.2/hr)',              doctor: 'Dr. Ahmad' },
      { id: 'mh2', date: '2025-01-22', type: 'Medication',  note: 'Prescribed CPAP therapy (8 cmH2O)',                      doctor: 'Dr. Ahmad' },
      { id: 'mh3', date: '2024-11-05', type: 'Lab Result',  note: 'Overnight polysomnography — AHI 8.2, SpO2 nadir 91%',   doctor: 'Dr. Lim'   },
    ],
  },
  {
    id: '3',
    name: 'Siti Aminah',
    age: 28,
    lastSpo2: 94,
    lastHr: 62,
    criticalEvents: 0,
    status: 'sleeping',
    weight: 55,
    height: 160,
    medicalHistory: [
      { id: 'mh1', date: '2025-04-18', type: 'Diagnosis',  note: 'Upper airway resistance syndrome, mild',      doctor: 'Dr. Farah' },
      { id: 'mh2', date: '2025-02-09', type: 'Lab Result', note: 'CBC and thyroid panel — within normal limits', doctor: 'Dr. Farah' },
    ],
  },
  {
    id: '4',
    name: 'Rahman Ismail',
    age: 51,
    lastSpo2: 88,
    lastHr: 71,
    criticalEvents: 5,
    status: 'critical',
    weight: 95,
    height: 168,
    medicalHistory: [
      { id: 'mh1', date: '2025-05-01', type: 'Diagnosis',  note: 'Severe obstructive sleep apnea (AHI 34/hr)',        doctor: 'Dr. Ahmad' },
      { id: 'mh2', date: '2025-04-15', type: 'Medication', note: 'BiPAP — IPAP 14 cmH2O / EPAP 8 cmH2O',             doctor: 'Dr. Ahmad' },
      { id: 'mh3', date: '2025-03-30', type: 'Medication', note: 'Supplemental oxygen (2 L/min nasal cannula)',       doctor: 'Dr. Ahmad' },
      { id: 'mh4', date: '2025-01-12', type: 'Lab Result', note: 'ABG: pH 7.36, PaO2 68 mmHg, PaCO2 48 mmHg',       doctor: 'Dr. Lim'   },
    ],
  },
];

const STATUS_CONFIG = {
  active:   { bg: '#0a2010', border: '#14532d', dot: '#22c55e', text: '#4ade80', label: 'Active'   },
  sleeping: { bg: '#0a0f2a', border: '#1e3a5f', dot: '#60a5fa', text: '#93c5fd', label: 'Sleeping' },
  critical: { bg: '#3d1010', border: '#7f1d1d', dot: '#ef4444', text: '#f87171', label: 'Critical' },
};

// Shown in place of the static status pill while the patient is streaming.
const LIVE_CONFIG = { bg: '#0a2010', border: '#14532d', dot: '#22c55e', text: '#4ade80', label: 'LIVE' };

function formatClock(ts) {
  const d   = new Date(ts);
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
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

function PatientCard({ patient, snapshot, liveCritical, now, onPress }) {
  // A patient is live only while fresh messages bearing its patientId arrive;
  // otherwise the card falls back to the seeded record.
  const isLive   = !!snapshot && (now - snapshot.lastSeen) < PATIENT_LIVE_WINDOW_MS;
  const spo2     = isLive && snapshot.spo2 != null ? Math.round(snapshot.spo2) : patient.lastSpo2;
  const hr       = isLive && snapshot.heartRate != null ? Math.round(snapshot.heartRate) : patient.lastHr;
  const critical = isLive ? liveCritical : patient.criticalEvents;
  const status   = isLive ? LIVE_CONFIG : (STATUS_CONFIG[patient.status] || STATUS_CONFIG.active);
  const spo2Color = spo2 < 90 ? '#f87171'
                  : spo2 < 95 ? '#fbbf24' : '#4ade80';
  const bmi      = computeBmi(patient.weight, patient.height);
  const lastSeen = snapshot ? ` · last seen ${formatClock(snapshot.lastSeen)}` : '';

  return (
    <TouchableOpacity
      style={styles.card}
      onPress={onPress}
      activeOpacity={0.75}
    >
      {/* Top row: name + status badge */}
      <View style={styles.cardHeader}>
        <View style={styles.avatarWrap}>
          <MaterialCommunityIcons name="account" size={22} color="#818cf8" />
        </View>
        <View style={styles.nameBlock}>
          <Text style={styles.patientName}>{patient.name}</Text>
          <Text style={styles.patientAge}>Age {patient.age}{lastSeen}</Text>
        </View>
        <View style={[styles.badge, { backgroundColor: status.bg, borderColor: status.border }]}>
          <View style={[styles.badgeDot, { backgroundColor: status.dot }]} />
          <Text style={[styles.badgeText, { color: status.text }]}>{status.label}</Text>
        </View>
      </View>

      {/* Divider */}
      <View style={styles.divider} />

      {/* Vitals row — 4 columns */}
      <View style={styles.vitalsRow}>
        <View style={styles.vitalItem}>
          <Text style={styles.vitalLabel}>SpO2</Text>
          <Text style={[styles.vitalValue, { color: spo2Color }]}>{spo2}%</Text>
        </View>
        <View style={styles.vitalSep} />
        <View style={styles.vitalItem}>
          <Text style={styles.vitalLabel}>Heart Rate</Text>
          <Text style={styles.vitalValue}>{hr} bpm</Text>
        </View>
        <View style={styles.vitalSep} />
        <View style={styles.vitalItem}>
          <Text style={styles.vitalLabel}>Critical</Text>
          <Text style={[
            styles.vitalValue,
            { color: critical > 0 ? '#f87171' : '#4ade80' },
          ]}>
            {critical}
          </Text>
        </View>
        <View style={styles.vitalSep} />
        <View style={styles.vitalItem}>
          <Text style={styles.vitalLabel}>BMI</Text>
          <Text style={[styles.vitalValue, { color: bmiColor(bmi) }]}>{bmi}</Text>
        </View>
      </View>

      {/* Chevron hint */}
      <MaterialCommunityIcons
        name="chevron-right"
        size={18}
        color="#333"
        style={styles.chevron}
      />
    </TouchableOpacity>
  );
}

export default function PatientListScreen({ navigation }) {
  const { patientSnapshots, sessionStats } = useSleep();
  const now = useNow();

  return (
    <View style={styles.root}>
      {/* Section header */}
      <View style={styles.pageHeader}>
        <Text style={styles.pageTitle}>My Patients</Text>
        <Text style={styles.pageSubtitle}>{MOCK_PATIENTS.length} patients monitored</Text>
      </View>

      <FlatList
        data={MOCK_PATIENTS}
        keyExtractor={item => item.id}
        contentContainerStyle={styles.list}
        showsVerticalScrollIndicator={false}
        renderItem={({ item }) => (
          <PatientCard
            patient={item}
            snapshot={item.patientId ? patientSnapshots[item.patientId] : null}
            liveCritical={sessionStats.critical}
            now={now}
            onPress={() => navigation.navigate('PatientDetail', { patient: item })}
          />
        )}
        ItemSeparatorComponent={() => <View style={{ height: 12 }} />}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#0a0a0f',
  },
  pageHeader: {
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 12,
  },
  pageTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: '#e2e8f0',
  },
  pageSubtitle: {
    fontSize: 12,
    color: '#555',
    marginTop: 4,
    letterSpacing: 0.3,
  },
  list: {
    paddingHorizontal: 20,
    paddingBottom: 32,
  },

  // Card
  card: {
    backgroundColor: '#0f0f1a',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#1a1a2e',
    padding: 16,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  avatarWrap: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: '#13132a',
    borderWidth: 1,
    borderColor: '#2a2a4a',
    alignItems: 'center',
    justifyContent: 'center',
  },
  nameBlock: {
    flex: 1,
  },
  patientName: {
    fontSize: 15,
    fontWeight: '600',
    color: '#e2e8f0',
  },
  patientAge: {
    fontSize: 12,
    color: '#555',
    marginTop: 2,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 20,
    borderWidth: 1,
  },
  badgeDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 0.3,
  },

  // Vitals
  divider: {
    height: 1,
    backgroundColor: '#1a1a2e',
    marginVertical: 12,
  },
  vitalsRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  vitalItem: {
    flex: 1,
    alignItems: 'center',
  },
  vitalLabel: {
    fontSize: 9,
    color: '#555',
    letterSpacing: 0.3,
    textTransform: 'uppercase',
    marginBottom: 4,
  },
  vitalValue: {
    fontSize: 15,
    fontWeight: '700',
    color: '#e2e8f0',
  },
  vitalSep: {
    width: 1,
    height: 32,
    backgroundColor: '#1a1a2e',
  },
  chevron: {
    position: 'absolute',
    right: 16,
    bottom: 16,
  },
});
