import { useCallback, useState } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import EventLog from '../../components/EventLog';
import { useSleep, PATIENT_LIVE_WINDOW_MS } from '../../context/SleepContext';
import { useNow } from '../../hooks/useNow';
import { useRoster } from './rosterLive';
import { mergeAlerts } from './alertHistory';
import { fetchAlertHistory } from '../../auth/apiAuth';
import { alertSubtitleCounts } from '../../config/displayText';

// The doctor's alert inbox: persisted history (GET /alerts) merged with the
// live eventLog, captioned with the currently-streaming patient — the roster
// names them via the deviceId their watch publishes under.
export default function DoctorAlertsScreen() {
  const { eventLog, sessionStats, deviceSnapshots } = useSleep();
  const now = useNow();
  const roster = useRoster();

  // Persisted alert history. null = first fetch still in flight or it failed —
  // the screen then shows the live log alone, as before (degrade, never block).
  const [history, setHistory] = useState(null);

  useFocusEffect(useCallback(() => {
    let cancelled = false;
    fetchAlertHistory()
      .then(rows => { if (!cancelled) setHistory(rows); })
      .catch(() => { /* keep whatever history we have; live rows still show */ });
    return () => { cancelled = true; };
  }, []));

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

  const events = mergeAlerts(eventLog, history, roster);

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
        events={events}
        emptyMessage="No alerts recorded yet — Critical/Important events appear here."
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
