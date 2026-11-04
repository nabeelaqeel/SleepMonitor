import { View, Text, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useSleep } from '../context/SleepContext';
import EventLog from '../components/EventLog';

export default function AlertsScreen() {
  const { eventLog, sessionStats } = useSleep();

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Tonight's events</Text>
        <Text style={styles.subtitle}>
          {sessionStats.critical} critical · {sessionStats.important} important
        </Text>
      </View>

      <EventLog events={eventLog} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0a0f' },
  header:    { paddingHorizontal: 20, paddingTop: 20, paddingBottom: 12 },
  title:     { fontSize: 26, fontWeight: '700', color: '#fff', marginBottom: 4 },
  subtitle:  { fontSize: 13, color: '#555' },
});
