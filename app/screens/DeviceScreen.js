import { useState, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  ScrollView,
  RefreshControl,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useFocusEffect } from '@react-navigation/native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { fetchDevices, bindDevice, linkDoctor } from '../auth/apiAuth';

// The API owns the linkage; this cache only mirrors the last linkDoctor
// response so the card survives remounts — re-linking (idempotent) refreshes it.
const LINKED_DOCTOR_KEY = 'linked_doctor';

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString();
}

function DeviceRow({ device }) {
  return (
    <View style={styles.deviceRow}>
      <View style={styles.deviceIcon}>
        <MaterialCommunityIcons name="watch-variant" size={22} color="#818cf8" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.deviceName}>{device.display_name || 'Unnamed watch'}</Text>
        <Text style={styles.deviceMeta}>
          {device.device_id}
          {device.created_at ? ` · connected ${formatDate(device.created_at)}` : ''}
        </Text>
      </View>
      <View style={styles.boundBadge}>
        <Text style={styles.boundText}>Bound</Text>
      </View>
    </View>
  );
}

export default function DeviceScreen() {
  const [devices, setDevices]     = useState([]);
  const [loading, setLoading]     = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError]         = useState('');
  const [notice, setNotice]       = useState('');

  const [deviceId, setDeviceId]       = useState('');
  const [displayName, setDisplayName] = useState('');
  const [pairCode, setPairCode]       = useState('');
  const [linkedDoctor, setLinkedDoctor] = useState(null);
  const [formBusy, setFormBusy]       = useState(''); // 'bind' | 'link' | ''

  async function load({ silent = false } = {}) {
    if (!silent) setError('');
    if (silent) setRefreshing(true); else setLoading(true);
    try {
      const list = await fetchDevices();
      setDevices(list);
      setError('');
    } catch (err) {
      setError(err.message || 'Could not load your devices');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useFocusEffect(
    useCallback(() => {
      load();
      // Linked-doctor mirror: re-read from storage, never re-fetched (no GET for it).
      AsyncStorage.getItem(LINKED_DOCTOR_KEY)
        .then(raw => raw && setLinkedDoctor(JSON.parse(raw)))
        .catch(() => {});
      return () => {};
    }, [])
  );

  async function handleBind() {
    setError('');
    setNotice('');
    if (!deviceId.trim()) {
      setError('Enter a device ID from the watch');
      return;
    }
    setFormBusy('bind');
    try {
      await bindDevice(deviceId.trim(), displayName);
      setDeviceId('');
      setDisplayName('');
      setNotice('Watch connected');
      await load({ silent: true });
    } catch (err) {
      // 409 etc. come verbatim from the API ("Device is already bound to another patient").
      setError(err.message || 'Could not bind device');
    } finally {
      setFormBusy('');
    }
  }

  async function handleLink() {
    setError('');
    setNotice('');
    if (pairCode.trim().length < 4) {
      setError('Enter the pairing code from your doctor');
      return;
    }
    setFormBusy('link');
    try {
      const result = await linkDoctor(pairCode.trim());
      if (result && result.doctor) {
        setLinkedDoctor(result.doctor);
        await AsyncStorage.setItem(LINKED_DOCTOR_KEY, JSON.stringify(result.doctor));
      }
      setPairCode('');
      setNotice('Linked to your doctor');
    } catch (err) {
      // 404 "Unknown pairing code" etc. surface verbatim.
      setError(err.message || 'Could not link to doctor');
    } finally {
      setFormBusy('');
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
    <ScrollView
      style={styles.root}
      contentContainerStyle={styles.scroll}
      showsVerticalScrollIndicator={false}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => load({ silent: true })}
          tintColor="#818cf8"
          colors={['#818cf8']}
        />
      }
    >
      {/* Error / notice banners */}
      {!!error && (
        <View style={styles.banner}>
          <MaterialCommunityIcons name="alert-circle-outline" size={16} color="#f87171" />
          <Text style={[styles.bannerText, { color: '#f87171' }]}>{error}</Text>
        </View>
      )}
      {!!notice && (
        <View style={styles.banner}>
          <MaterialCommunityIcons name="check-circle-outline" size={16} color="#4ade80" />
          <Text style={[styles.bannerText, { color: '#4ade80' }]}>{notice}</Text>
        </View>
      )}

      {/* ── Linked doctor ── */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>My Doctor</Text>
        {linkedDoctor ? (
          <View style={styles.linkedRow}>
            <MaterialCommunityIcons name="stethoscope" size={22} color="#4ade80" />
            <View style={{ flex: 1 }}>
              <Text style={styles.deviceName}>{linkedDoctor.name}</Text>
              <Text style={styles.deviceMeta}>{linkedDoctor.email}</Text>
            </View>
            <View style={[styles.boundBadge, { backgroundColor: '#0a2010', borderColor: '#14532d' }]}>
              <Text style={[styles.boundText, { color: '#4ade80' }]}>Linked</Text>
            </View>
          </View>
        ) : (
          <Text style={styles.cardHint}>
            Not linked yet — enter the 12-character code your doctor shares with you.
          </Text>
        )}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Pairing code</Text>
          <View style={styles.inputWrap}>
            <MaterialCommunityIcons name="key-outline" size={18} color="#555" style={styles.inputIcon} />
            <TextInput
              style={styles.input}
              placeholder="e.g. AB12CD34EF56"
              placeholderTextColor="#444"
              autoCapitalize="characters"
              autoCorrect={false}
              value={pairCode}
              onChangeText={setPairCode}
            />
          </View>
        </View>
        <TouchableOpacity
          style={[styles.button, formBusy === 'link' && styles.buttonDisabled]}
          onPress={handleLink}
          disabled={formBusy !== ''}
          activeOpacity={0.8}
        >
          {formBusy === 'link'
            ? <ActivityIndicator color="#fff" size="small" />
            : <Text style={styles.buttonText}>Link to Doctor</Text>}
        </TouchableOpacity>
      </View>

      {/* ── Bound devices ── */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>My Devices</Text>
        {devices.length === 0 ? (
          <View style={styles.emptyWrap}>
            <MaterialCommunityIcons name="watch-off" size={30} color="#333" />
            <Text style={styles.emptyText}>No watch connected</Text>
            <Text style={styles.emptyHint}>Bind your watch below to start streaming readings.</Text>
          </View>
        ) : (
          devices.map(d => <DeviceRow key={d.device_id} device={d} />)
        )}
      </View>

      {/* ── Bind form ── */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Connect a Watch</Text>
        <Text style={styles.cardHint}>
          Enter the device ID shown on the watch. Re-connecting the same ID updates its name.
        </Text>
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Device ID</Text>
          <View style={styles.inputWrap}>
            <MaterialCommunityIcons name="identifier" size={18} color="#555" style={styles.inputIcon} />
            <TextInput
              style={styles.input}
              placeholder="e.g. watch-001"
              placeholderTextColor="#444"
              autoCapitalize="none"
              autoCorrect={false}
              value={deviceId}
              onChangeText={setDeviceId}
            />
          </View>
        </View>
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Display name (optional)</Text>
          <View style={styles.inputWrap}>
            <MaterialCommunityIcons name="tag-outline" size={18} color="#555" style={styles.inputIcon} />
            <TextInput
              style={styles.input}
              placeholder="e.g. Aqeel's watch"
              placeholderTextColor="#444"
              value={displayName}
              onChangeText={setDisplayName}
            />
          </View>
        </View>
        <TouchableOpacity
          style={[styles.button, formBusy === 'bind' && styles.buttonDisabled]}
          onPress={handleBind}
          disabled={formBusy !== ''}
          activeOpacity={0.8}
        >
          {formBusy === 'bind'
            ? <ActivityIndicator color="#fff" size="small" />
            : <Text style={styles.buttonText}>Connect Watch</Text>}
        </TouchableOpacity>
      </View>
    </ScrollView>
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
  scroll: {
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 32,
  },

  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#0f0f1a',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#1a1a2e',
    padding: 12,
    marginBottom: 12,
  },
  bannerText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 18,
  },

  card: {
    backgroundColor: '#0f0f1a',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#1a1a2e',
    padding: 16,
    marginBottom: 14,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#e2e8f0',
    marginBottom: 12,
  },
  cardHint: {
    fontSize: 12,
    color: '#666',
    lineHeight: 18,
    marginBottom: 12,
  },

  linkedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: '#0a0a0f',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#1a1a2e',
    padding: 12,
    marginBottom: 12,
  },

  deviceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: '#0a0a0f',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#1a1a2e',
    padding: 12,
    marginBottom: 10,
  },
  deviceIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: '#13132a',
    borderWidth: 1,
    borderColor: '#2a2a4a',
    alignItems: 'center',
    justifyContent: 'center',
  },
  deviceName: {
    fontSize: 14,
    fontWeight: '600',
    color: '#e2e8f0',
  },
  deviceMeta: {
    fontSize: 12,
    color: '#555',
    marginTop: 2,
  },
  boundBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#2a2a4a',
    backgroundColor: '#13131f',
  },
  boundText: {
    fontSize: 11,
    fontWeight: '600',
    color: '#9ca3af',
    letterSpacing: 0.3,
  },

  emptyWrap: {
    alignItems: 'center',
    paddingVertical: 18,
    gap: 6,
  },
  emptyText: {
    fontSize: 14,
    color: '#888',
    fontWeight: '500',
  },
  emptyHint: {
    fontSize: 12,
    color: '#555',
    textAlign: 'center',
  },

  inputGroup: {
    marginBottom: 14,
  },
  label: {
    fontSize: 12,
    color: '#888',
    marginBottom: 8,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  inputWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0a0a0f',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#1a1a2e',
    paddingHorizontal: 12,
    height: 48,
  },
  inputIcon: {
    marginRight: 8,
  },
  input: {
    flex: 1,
    color: '#e2e8f0',
    fontSize: 15,
  },

  button: {
    backgroundColor: '#818cf8',
    borderRadius: 12,
    height: 48,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '600',
    letterSpacing: 0.3,
  },
});
