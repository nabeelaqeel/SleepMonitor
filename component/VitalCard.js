import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function VitalCard({ label, value, unit, color, warning }) {
  return (
    <View style={[styles.card, warning && styles.cardWarning]}>
      <Text style={styles.label}>{label}</Text>
      <Text style={[styles.value, { color: color || '#ffffff' }]}>
        {value}
        {unit ? <Text style={styles.unit}> {unit}</Text> : null}
      </Text>
      {warning ? (
        <Text style={styles.warningText}>{warning}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    width: '47%',
    backgroundColor: '#13131f',
    borderRadius: 12,
    padding: 14,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
  },
  cardWarning: {
    borderColor: '#7f1d1d',
    backgroundColor: '#1a0d0d',
  },
  label: {
    fontSize: 11,
    color: '#555',
    marginBottom: 6,
    fontWeight: '500',
  },
  value: {
    fontSize: 24,
    fontWeight: '700',
    color: '#fff',
  },
  unit: {
    fontSize: 13,
    fontWeight: '400',
    color: '#888',
  },
  warningText: {
    fontSize: 10,
    color: '#f87171',
    marginTop: 4,
  },
});