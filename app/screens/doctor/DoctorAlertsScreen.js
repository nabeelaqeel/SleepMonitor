import { View, Text, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import EventLog from '../../components/EventLog';
import { useSleep, PATIENT_LIVE_WINDOW_MS } from '../../context/SleepContext';
import { useNow } from '../../hooks/useNow';
import { useRoster } from './rosterLive';
import { alertSubtitleCounts } from '../../config/displayText';

// The doctor's alert inbox. The app currently receives a single live stream, so
// this list is that session's events, captioned with the owning patient — the
// roster names them via the deviceId their watch publishes under.
export default function DoctorAlertsScreen() {
  const { eventLog, sessionStats, deviceSnapshots } = useSleep();
  const now = useNow();
  const roster = useRoster();

  // Freshest streaming device; fall back to the most recently seen one so the
  // caption still names the session after it ends.
  const deviceIds = Object.keys(deviceSnapshots);
  const liveDeviceId = deviceIds.find(id => (now - deviceSnapshots[id].lastSeen) < PATIENT_LIVE_WINDOW_MS) || null;
  const lastDeviceId = deviceIds.length
    ? deviceIds.reduce((a, b) => (deviceSnapshots[a].lastSeen >= deviceSnapshots[b].lastSeen ? a : b))
    : null;
  const sessionId = liveDeviceId || lastDeviceId;

  // Roster names the streamer; an unbound device still gets an honest caption
  // (fetch failures degrade to the unbound label — alerts never lose their rows).
  const rosterPatient = sessionId
    ? roster.find(p => p.devices.some(d => d.device_id === sessionId)) || null
    : null;
  const streamerLabel = rosterPatient ? rosterPatient.name : 'Unbound device';

  const caption = sessionId
    ? liveDeviceId
      ? `Live session — ${streamerLabel} · ${sessionId}`
      : `Session ended — ${streamerLabel} · ${sessionId}`
    : null;

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Alerts</Text>
        <Text style={styles.subtitle}>
          {alertSubtitleCounts(sessionStats.critical, sessionStats.important)}
        </Text>
        {caption && (
          <View style={styles.sessionRow}>
            <View style={[styles.sessionDot, { backgroundColor: liveDeviceId ? '#22c55e' : '#6b7280' }]} />
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
