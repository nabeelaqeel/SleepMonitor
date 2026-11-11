import {
  View, Text, StyleSheet, ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import {
  AI_BAND_LABELS, DISCLAIMER, aboutBulletText,
} from '../config/displayText';

// Full "About / Disclaimer" screen; every string comes from config/displayText.js (wording tunable without code changes).
export default function AboutScreen() {
  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        {/* Title (the tab header shows "About" on the patient side; this
            heading is the in-screen title for the bare-header doctor side) */}
        <View style={styles.titleRow}>
          <MaterialCommunityIcons name="information-outline" size={24} color="#818cf8" />
          <Text style={styles.title}>{DISCLAIMER.about.title}</Text>
        </View>

        {/* Intro */}
        <Text style={styles.intro}>{DISCLAIMER.about.intro}</Text>

        {/* Bullets */}
        <View style={styles.bulletsCard}>
          {DISCLAIMER.about.bullets.map((bullet, i) => (
            <View key={i} style={styles.bulletRow}>
              <Text style={styles.bulletDot}>•</Text>
              <Text style={styles.bulletText}>{aboutBulletText(bullet)}</Text>
            </View>
          ))}
        </View>

        {/* Sample of the indicator names, as the user actually sees them, so
            this screen stays consistent with the results screen wording */}
        <View style={styles.tiersCard}>
          <Text style={styles.tiersTitle}>Indicators you may see</Text>
          {Object.values(AI_BAND_LABELS).map(label => (
            <View key={label} style={styles.tierRow}>
              <View style={styles.tierDot} />
              <Text style={styles.tierText}>{label}</Text>
            </View>
          ))}
        </View>

        {/* Closing warning */}
        <View style={styles.closingCard}>
          <MaterialCommunityIcons name="alert-circle-outline" size={16} color="#fbbf24" />
          <Text style={styles.closingText}>{DISCLAIMER.about.closing}</Text>
        </View>

        {/* Footer */}
        <Text style={styles.footer}>{DISCLAIMER.footer}</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container:   { flex: 1, backgroundColor: '#0a0a0f' },
  scroll:      { padding: 20, paddingBottom: 40 },
  titleRow:    { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 14 },
  title:       { fontSize: 24, fontWeight: '700', color: '#fff', flex: 1 },
  intro:       { fontSize: 13, color: '#c4c9d4', lineHeight: 20, marginBottom: 16 },
  bulletsCard: {
    backgroundColor: '#13131f', borderRadius: 12,
    padding: 16, marginBottom: 16,
    borderWidth: 0.5, borderColor: '#1e1e30', gap: 10,
  },
  bulletRow:   { flexDirection: 'row', gap: 6 },
  bulletDot:   { fontSize: 13, color: '#818cf8', lineHeight: 19 },
  bulletText:  { fontSize: 12, color: '#9ca3af', lineHeight: 19, flex: 1 },
  tiersCard:   {
    backgroundColor: '#13131f', borderRadius: 12,
    padding: 16, marginBottom: 16,
    borderWidth: 0.5, borderColor: '#1e1e30', gap: 8,
  },
  tiersTitle:  { fontSize: 11, color: '#555', letterSpacing: 0.5, textTransform: 'uppercase', marginBottom: 2 },
  tierRow:     { flexDirection: 'row', alignItems: 'center', gap: 8 },
  tierDot:     { width: 7, height: 7, borderRadius: 4, backgroundColor: '#818cf8' },
  tierText:    { fontSize: 12, color: '#e2e8f0', flex: 1 },
  closingCard: {
    backgroundColor: '#2d1f07', borderRadius: 12,
    padding: 14, marginBottom: 16,
    borderWidth: 1, borderColor: '#78350f',
    flexDirection: 'row', gap: 8, alignItems: 'flex-start',
  },
  closingText: { fontSize: 12, color: '#fbbf24', lineHeight: 18, flex: 1 },
  footer:      { fontSize: 10, color: '#4b5563', textAlign: 'center', lineHeight: 15, marginTop: 8 },
});
