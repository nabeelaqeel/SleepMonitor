import { useState, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Modal,
  RefreshControl,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { useSleep } from '../../context/SleepContext';
import { useNow } from '../../hooks/useNow';
import { fetchPatients, getPairingCode } from '../../auth/apiAuth';
import { mapRosterPatient, pickLiveDevice } from './rosterLive';

// Neutral grey for record values on a non-streaming card — roster readings are history, not current.
const RECORD_COLOR = '#9ca3af';

// Shown in place of the static status pill while the patient is streaming.
const LIVE_CONFIG = { bg: '#0a2010', border: '#14532d', dot: '#22c55e', text: '#4ade80', label: 'LIVE' };

// Every non-live card reads "Offline" — roster values are recorded snapshots, not current.
const OFFLINE_CONFIG = { bg: '#13131f', border: '#2a2a4a', dot: '#6b7280', text: RECORD_COLOR, label: 'Offline' };

function formatClock(ts) {
  const d   = new Date(ts);
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function PatientCard({ patient, snapshot, now, onPress }) {
  // LIVE joins through the registry: any bound device streaming keeps the card
  // fresh; the freshest device's snapshot overlays its vitals.
  const isLive   = !!snapshot;
  const spo2     = isLive && snapshot.spo2 != null ? Math.round(snapshot.spo2) : patient.lastSpo2;
  const hr       = isLive && snapshot.heartRate != null ? Math.round(snapshot.heartRate) : patient.lastHr;
  const status   = isLive ? LIVE_CONFIG : OFFLINE_CONFIG;
  const spo2Color = !isLive ? RECORD_COLOR
                  : spo2 == null ? RECORD_COLOR
                  : spo2 < 90 ? '#f87171'
                  : spo2 < 95 ? '#fbbf24' : '#4ade80';
  const missing  = patient.lastSession ? patient.lastSession.missing_readings || 0 : 0;
  const lastSeen = isLive ? ` · last seen ${formatClock(snapshot.lastSeen)}` : '';

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
          <View style={styles.nameRow}>
            <Text style={styles.patientName}>{patient.name}</Text>
            {patient.devices.length > 0 && (
              <MaterialCommunityIcons name="watch-variant" size={15} color="#818cf8" />
            )}
          </View>
          <Text style={styles.patientMeta} numberOfLines={1}>
            {patient.email || `ID #${patient.id}`}{lastSeen}
          </Text>
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
          <Text style={[styles.vitalValue, { color: spo2Color }]}>
            {spo2 == null ? '--' : `${Math.round(spo2)}%`}
          </Text>
        </View>
        <View style={styles.vitalSep} />
        <View style={styles.vitalItem}>
          <Text style={styles.vitalLabel}>Heart Rate</Text>
          <Text style={[styles.vitalValue, { color: isLive || hr != null ? '#e2e8f0' : RECORD_COLOR }]}>
            {hr == null ? '--' : `${Math.round(hr)} bpm`}
          </Text>
        </View>
        <View style={styles.vitalSep} />
        <View style={styles.vitalItem}>
          <Text style={styles.vitalLabel}>Session</Text>
          <Text style={[
            styles.vitalValue,
            { color: !isLive && missing > 0 ? '#fbbf24' : '#e2e8f0' },
          ]}>
            {patient.lastSession ? patient.lastSession.total_readings : '--'}
          </Text>
        </View>
        <View style={styles.vitalSep} />
        <View style={styles.vitalItem}>
          <Text style={styles.vitalLabel}>Devices</Text>
          <Text style={[styles.vitalValue, { color: patient.devices.length > 0 ? '#e2e8f0' : RECORD_COLOR }]}>
            {patient.devices.length}
          </Text>
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
  const { deviceSnapshots } = useSleep();
  const now = useNow();

  const [patients, setPatients]   = useState([]);
  const [loading, setLoading]     = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError]         = useState('');

  const [pairingOpen, setPairingOpen] = useState(false);
  const [pairingCode, setPairingCode] = useState('');
  const [pairingLoading, setPairingLoading] = useState(false);
  const [pairingError, setPairingError] = useState('');
  const [copied, setCopied] = useState(false);

  const loadPatients = useCallback(async ({ silent = false } = {}) => {
    if (silent) setRefreshing(true); else setLoading(true);
    try {
      const roster = await fetchPatients();
      setPatients(roster.map(mapRosterPatient));
      setError('');
    } catch (err) {
      setError(err.message || 'Could not load your patients');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // The roster is API-owned — always re-fetch when the tab regains focus.
  useFocusEffect(
    useCallback(() => {
      loadPatients();
      return () => {};
    }, [loadPatients])
  );

  async function openPairing() {
    setPairingOpen(true);
    setPairingError('');
    setCopied(false);
    setPairingCode('');
    setPairingLoading(true);
    try {
      setPairingCode(await getPairingCode());
    } catch (err) {
      setPairingError(err.message || 'Could not fetch pairing code');
    } finally {
      setPairingLoading(false);
    }
  }

  async function copyCode() {
    if (!pairingCode) return;
    try {
      await Clipboard.setStringAsync(pairingCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  if (loading) {
    return (
      <View style={[styles.root, styles.center]}>
        <ActivityIndicator size="large" color="#818cf8" />
      </View>
    );
  }

  return (
    <View style={styles.root}>
      {/* Section header + pairing control */}
      <View style={styles.pageHeader}>
        <View style={styles.pageHeaderRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.pageTitle}>My Patients</Text>
            <Text style={styles.pageSubtitle}>{patients.length} patients monitored</Text>
          </View>
          <TouchableOpacity
            style={styles.pairBtn}
            onPress={openPairing}
            activeOpacity={0.8}
          >
            <MaterialCommunityIcons name="key-variant" size={20} color="#818cf8" />
          </TouchableOpacity>
        </View>
      </View>

      {error ? (
        <View style={styles.stateWrap}>
          <MaterialCommunityIcons name="cloud-off-outline" size={34} color="#f87171" />
          <Text style={styles.stateText}>{error}</Text>
          <TouchableOpacity style={styles.stateBtn} onPress={() => loadPatients()}>
            <Text style={styles.stateBtnText}>Retry</Text>
          </TouchableOpacity>
        </View>
      ) : patients.length === 0 ? (
        <View style={styles.stateWrap}>
          <MaterialCommunityIcons name="account-multiple-outline" size={34} color="#333" />
          <Text style={styles.stateText}>No patients yet — share your pairing code</Text>
          <TouchableOpacity style={styles.stateBtn} onPress={openPairing}>
            <Text style={styles.stateBtnText}>Show pairing code</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={patients}
          keyExtractor={item => item.id}
          contentContainerStyle={styles.list}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => loadPatients({ silent: true })}
              tintColor="#818cf8"
              colors={['#818cf8']}
            />
          }
          renderItem={({ item }) => (
            <PatientCard
              patient={item}
              snapshot={pickLiveDevice(item, deviceSnapshots, now)}
              now={now}
              onPress={() => navigation.navigate('PatientDetail', { patient: item })}
            />
          )}
          ItemSeparatorComponent={() => <View style={{ height: 12 }} />}
        />
      )}

      {/* ── Pairing code modal ── */}
      <Modal
        visible={pairingOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setPairingOpen(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <MaterialCommunityIcons name="key-variant" size={34} color="#818cf8" />
            <Text style={styles.modalTitle}>Patient pairing code</Text>
            {pairingLoading ? (
              <ActivityIndicator color="#818cf8" style={{ marginVertical: 22 }} />
            ) : pairingError ? (
              <>
                <Text style={styles.modalError}>{pairingError}</Text>
                <TouchableOpacity style={styles.stateBtn} onPress={openPairing}>
                  <Text style={styles.stateBtnText}>Retry</Text>
                </TouchableOpacity>
              </>
            ) : (
              <>
                <Text selectable style={styles.pairingCode}>{pairingCode}</Text>
                <Text style={styles.modalCaption}>Share this code with your patient</Text>
                <TouchableOpacity
                  style={[styles.copyBtn, copied && styles.copyBtnDone]}
                  onPress={copyCode}
                  activeOpacity={0.8}
                >
                  <MaterialCommunityIcons
                    name={copied ? 'check' : 'content-copy'}
                    size={16}
                    color={copied ? '#4ade80' : '#e2e8f0'}
                  />
                  <Text style={[styles.copyText, copied && { color: '#4ade80' }]}>
                    {copied ? 'Copied' : 'Copy code'}
                  </Text>
                </TouchableOpacity>
              </>
            )}
            <TouchableOpacity
              onPress={() => setPairingOpen(false)}
              style={styles.modalClose}
              disabled={pairingLoading}
            >
              <Text style={styles.modalCloseText}>Close</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#0a0a0f',
  },
  center: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  pageHeader: {
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 12,
  },
  pageHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
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
  pairBtn: {
    width: 42,
    height: 42,
    borderRadius: 12,
    backgroundColor: '#13132a',
    borderWidth: 1,
    borderColor: '#2a2a4a',
    alignItems: 'center',
    justifyContent: 'center',
  },
  list: {
    paddingHorizontal: 20,
    paddingBottom: 32,
  },

  stateWrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    paddingHorizontal: 32,
  },
  stateText: {
    fontSize: 14,
    color: '#888',
    textAlign: 'center',
    lineHeight: 20,
  },
  stateBtn: {
    backgroundColor: '#13132a',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#2a2a4a',
    paddingHorizontal: 18,
    paddingVertical: 10,
    marginTop: 4,
  },
  stateBtnText: {
    color: '#818cf8',
    fontSize: 14,
    fontWeight: '600',
  },

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
  nameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  patientName: {
    fontSize: 15,
    fontWeight: '600',
    color: '#e2e8f0',
  },
  patientMeta: {
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

  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  modalCard: {
    width: '100%',
    backgroundColor: '#0f0f1a',
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#2a2a4a',
    padding: 24,
    alignItems: 'center',
  },
  modalTitle: {
    fontSize: 17,
    fontWeight: '600',
    color: '#e2e8f0',
    marginTop: 12,
  },
  pairingCode: {
    fontSize: 30,
    fontWeight: '700',
    color: '#818cf8',
    letterSpacing: 4,
    marginVertical: 18,
  },
  modalCaption: {
    fontSize: 12,
    color: '#888',
    marginBottom: 16,
  },
  modalError: {
    color: '#f87171',
    fontSize: 13,
    textAlign: 'center',
    marginVertical: 18,
    lineHeight: 19,
  },
  copyBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#13132a',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#2a2a4a',
    paddingHorizontal: 18,
    paddingVertical: 10,
  },
  copyBtnDone: {
    borderColor: '#14532d',
  },
  copyText: {
    color: '#e2e8f0',
    fontSize: 14,
    fontWeight: '500',
  },
  modalClose: {
    marginTop: 16,
    padding: 6,
  },
  modalCloseText: {
    color: '#555',
    fontSize: 14,
  },
});
