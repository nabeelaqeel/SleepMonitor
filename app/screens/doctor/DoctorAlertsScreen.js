import { View, Text, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import EventLog from '../../components/EventLog';
import { useSleep, PATIENT_LIVE_WINDOW_MS } from '../../context/SleepContext';
import { useNow } from '../../hooks/useNow';
import { MOCK_PATIENTS } from '../../data/patients';
import { alertSubtitleCounts } from '../../config/displayText';

// The doctor's alert inbox. The app currently receives a single live stream, so
// this list is that session's events, captioned with the owning patient.
export default function DoctorAlertsScreen() {
  const { eventLog, sessionStats, patientSnapshots } = useSleep();
  const now = useNow();

  // A fresh snapshot means live; otherwise fall back to the most recently seen
  // patient so the caption still names the session after it ends.
  const ids    = Object.keys(patientSnapshots);
  const liveId = ids.find(id => (now - patientSnapshots[id].lastSeen) < PATIENT_LIVE_WINDOW_MS) || null;
  const lastId = ids.length
    ? ids.reduce((a, b) => (patientSnapshots[a].lastSeen >= patientSnapshots[b].lastSeen ? a : b))
    : null;
  const sessionPatient = MOCK_PATIENTS.find(p => p.patientId === (liveId || lastId)) || null;

  const caption = !sessionPatient
    ? null
    : liveId
      ? `Live session — ${sessionPatient.name} · ${sessionPatient.patientId}`
      : `Session ended — ${sessionPatient.name} · ${sessionPatient.patientId}`;

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Alerts</Text>
        <Text style={styles.subtitle}>
          {alertSubtitleCounts(sessionStats.critical, sessionStats.important)}
        </Text>
        {caption && (
          <View style={styles.sessionRow}>
            <View style={[styles.sessionDot, { backgroundColor: liveId ? '#22c55e' : '#6b7280' }]} />
            <Text style={styles.sessionText}>{caption}</Text>
          </View>
        )}
      </View>

      <EventLog
        events={eventLog}
        emptyMessage="No live session yet — alerts appear here while a patient streams."
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container:   { flex: 1, backgroundColor: '#0a0a0f' },
  header:      { paddingHorizontal: 20, paddingTop: 20, paddingBottom: 12 },
  title:       { fontSize: 26, fontWeight: '700', color: '#fff', marginBottom: 4 },
  subtitle:    { fontSize: 13, color: '#555' },
  sessionRow:  { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 6 },
  sessionDot:  { width: 7, height: 7, borderRadius: 4 },
  sessionText: { fontSize: 12, color: '#888' },
});
