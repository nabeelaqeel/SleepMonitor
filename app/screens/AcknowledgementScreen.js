import { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { DISCLAIMER } from '../config/displayText';

// First-launch gate shown before login (both roles); the storage write is the caller's via `onAgree`.
export default function AcknowledgementScreen({ onAgree }) {
  const [checked, setChecked] = useState(false);

  return (
    <SafeAreaView style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <MaterialCommunityIcons name="sleep" size={44} color="#818cf8" />
        <Text style={styles.title}>{DISCLAIMER.ackTitle}</Text>
        <Text style={styles.hint}>{DISCLAIMER.ackHint}</Text>
      </View>

      {/* Acknowledgement statement */}
      <View style={styles.statementCard}>
        <Text style={styles.statement}>{DISCLAIMER.acknowledgement}</Text>
      </View>

      {/* Checkbox row */}
      <TouchableOpacity
        style={styles.checkRow}
        onPress={() => setChecked(v => !v)}
        activeOpacity={0.7}
      >
        <MaterialCommunityIcons
          name={checked ? 'checkbox-marked' : 'checkbox-blank-outline'}
          size={22}
          color={checked ? '#818cf8' : '#666'}
        />
        <Text style={styles.checkText}>I have read and understood the above</Text>
      </TouchableOpacity>

      {/* Agree button — disabled until the box is ticked */}
      <TouchableOpacity
        style={[styles.agreeBtn, !checked && styles.agreeBtnDisabled]}
        onPress={onAgree}
        disabled={!checked}
        activeOpacity={0.75}
      >
        <Text style={[styles.agreeText, !checked && styles.agreeTextDisabled]}>
          {DISCLAIMER.agreeLabel}
        </Text>
      </TouchableOpacity>

      {/* Footer */}
      <Text style={styles.footer}>{DISCLAIMER.footer}</Text>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container:     { flex: 1, backgroundColor: '#0a0a0f', padding: 24, justifyContent: 'center' },
  header:        { alignItems: 'center', marginBottom: 26 },
  title:         { fontSize: 24, fontWeight: '700', color: '#fff', marginTop: 10 },
  hint:          { fontSize: 13, color: '#555', marginTop: 4 },
  statementCard: {
    backgroundColor: '#13131f', borderRadius: 12,
    borderWidth: 0.5, borderColor: '#2a2a4a',
    padding: 16, marginBottom: 16,
  },
  statement:     { fontSize: 13, color: '#c4c9d4', lineHeight: 20 },
  checkRow:      {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    paddingVertical: 8, marginBottom: 18,
  },
  checkText:     { fontSize: 12, color: '#9ca3af', flex: 1 },
  agreeBtn:      {
    backgroundColor: '#1a1a3a', borderRadius: 12,
    borderWidth: 1, borderColor: '#534AB7',
    paddingVertical: 14, alignItems: 'center',
  },
  agreeBtnDisabled: { opacity: 0.4 },
  agreeText:     { color: '#818cf8', fontSize: 15, fontWeight: '600' },
  agreeTextDisabled: { color: '#666' },
  footer:        {
    fontSize: 10, color: '#4b5563', textAlign: 'center',
    lineHeight: 15, marginTop: 22,
  },
});
