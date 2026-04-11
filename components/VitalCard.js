import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function VitalCard({ label, value, color = '#ffffff' }) {
  return (
    <View style={styles.card}>
      <Text style={styles.label}>{label}</Text>
      <Text style={[styles.value, { color }]}>{value}</Text>
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
  label: {
    fontSize: 11,
    color: '#666',
    marginBottom: 6,
    letterSpacing: 0.3,
  },
  value: {
    fontSize: 24,
    fontWeight: '700',
    color: '#ffffff',
  },
});