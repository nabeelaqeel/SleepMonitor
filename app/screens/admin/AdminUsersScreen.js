import { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  FlatList,
  Modal,
  RefreshControl,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
} from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { fetchAdminUsers, createAdminUser, resetAdminUserPassword } from '../../auth/apiAuth';

// Same validation floor as /auth/register — the server re-validates anyway,
// but catching the obvious ones client-side saves a round trip.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD_LEN = 8;

const ADMIN_ROLES = [
  { value: 'patient', label: 'Patient', icon: 'account-heart' },
  { value: 'doctor',  label: 'Doctor',  icon: 'doctor' },
  { value: 'admin',   label: 'Admin',   icon: 'shield-account' },
];

// Role badge colours follow the tier palette already used across the dark theme.
const ROLE_BADGE = {
  admin:   { color: '#818cf8', icon: 'shield-account' },
  doctor:  { color: '#fbbf24', icon: 'doctor' },
  patient: { color: '#4ade80', icon: 'account-heart' },
};

function initialOf(user) {
  const name  = (user.name  || '').trim();
  const email = (user.email || '').trim();
  return name.charAt(0).toUpperCase() || email.charAt(0).toUpperCase() || '?';
}

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function RolePicker({ value, onChange, disabled }) {
  return (
    <View style={styles.roleRow}>
      {ADMIN_ROLES.map(role => {
        const selected = value === role.value;
        return (
          <TouchableOpacity
            key={role.value}
            style={[styles.roleSegment, selected && styles.roleSegmentSelected, disabled && styles.btnDisabled]}
            onPress={() => onChange(role.value)}
            disabled={disabled}
            activeOpacity={0.8}
          >
            <MaterialCommunityIcons
              name={role.icon}
              size={18}
              color={selected ? '#fff' : '#555'}
            />
            <Text style={[styles.roleLabel, selected && styles.roleLabelSelected]}>{role.label}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

export default function AdminUsersScreen() {
  const [users, setUsers]           = useState([]);
  const [loading, setLoading]       = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [listError, setListError]   = useState('');
  const [notice, setNotice]         = useState('');

  const [createOpen, setCreateOpen]     = useState(false);
  const [email, setEmail]               = useState('');
  const [name, setName]                 = useState('');
  const [password, setPassword]         = useState('');
  const [role, setRole]                 = useState('patient');
  const [formError, setFormError]       = useState('');
  const [creating, setCreating]         = useState(false);

  const [resetTarget, setResetTarget]   = useState(null);
  const [newPassword, setNewPassword]   = useState('');
  const [resetError, setResetError]     = useState('');
  const [resetting, setResetting]       = useState(false);

  const loadUsers = useCallback(async ({ showSpinner = false } = {}) => {
    if (showSpinner) setLoading(true);
    setListError('');
    try {
      setUsers(await fetchAdminUsers());
    } catch (err) {
      setListError(err.message || 'Could not load users');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUsers({ showSpinner: true });
  }, [loadUsers]);

  async function onRefresh() {
    setRefreshing(true);
    await loadUsers();
    setRefreshing(false);
  }

  function openCreate() {
    setNotice('');
    setEmail('');
    setName('');
    setPassword('');
    setRole('patient');
    setFormError('');
    setCreateOpen(true);
  }

  async function submitCreate() {
    setFormError('');
    if (!EMAIL_PATTERN.test(email.trim())) {
      setFormError('Enter a valid email address.');
      return;
    }
    if (password.length < MIN_PASSWORD_LEN) {
      setFormError(`Password must be at least ${MIN_PASSWORD_LEN} characters.`);
      return;
    }

    setCreating(true);
    try {
      const user = await createAdminUser({ email, password, role, name });
      setCreateOpen(false);
      setNotice(`Created ${user.role} account for ${user.email}`);
      await loadUsers();
    } catch (err) {
      // 409/422 bodies arrive pre-flattened to a readable sentence from apiAuth.
      setFormError(err.message || 'Could not create user');
    } finally {
      setCreating(false);
    }
  }

  function openReset(user) {
    setNotice('');
    setResetTarget(user);
    setNewPassword('');
    setResetError('');
  }

  async function submitReset() {
    setResetError('');
    if (newPassword.length < MIN_PASSWORD_LEN) {
      setResetError(`Password must be at least ${MIN_PASSWORD_LEN} characters.`);
      return;
    }

    setResetting(true);
    try {
      const user = await resetAdminUserPassword(resetTarget.id, newPassword);
      setResetTarget(null);
      setNotice(`Password updated for ${user.email}`);
    } catch (err) {
      setResetError(err.message || 'Could not reset password');
    } finally {
      setResetting(false);
    }
  }

  function renderUser({ item }) {
    const badge = ROLE_BADGE[item.role] || ROLE_BADGE.patient;
    const displayName = (item.name || '').trim() || item.email.split('@')[0];
    return (
      <View style={styles.card}>
        <View style={styles.cardTop}>
          <View style={styles.avatar}>
            <Text style={styles.avatarLetter}>{initialOf(item)}</Text>
          </View>
          <View style={styles.identity}>
            <Text style={styles.name} numberOfLines={1}>{displayName}</Text>
            <Text style={styles.email} numberOfLines={1}>{item.email}</Text>
            <View style={styles.metaRow}>
              <View style={styles.roleBadge}>
                <MaterialCommunityIcons name={badge.icon} size={12} color={badge.color} />
                <Text style={[styles.roleBadgeText, { color: badge.color }]}>{item.role}</Text>
              </View>
              <Text style={styles.created}>Created {formatDate(item.created_at)}</Text>
            </View>
          </View>
          <TouchableOpacity
            style={styles.resetBtn}
            onPress={() => openReset(item)}
            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            activeOpacity={0.7}
          >
            <MaterialCommunityIcons name="lock-reset" size={18} color="#818cf8" />
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <FlatList
        data={users}
        keyExtractor={item => item.id}
        renderItem={renderUser}
        contentContainerStyle={styles.list}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#818cf8"
            colors={['#818cf8']}
          />
        }
        ListHeaderComponent={
          <View style={styles.header}>
            <View>
              <Text style={styles.pageTitle}>User management</Text>
              <Text style={styles.pageSubtitle}>{users.length} accounts provisioned</Text>
            </View>
            <TouchableOpacity style={styles.createBtn} onPress={openCreate} activeOpacity={0.8}>
              <MaterialCommunityIcons name="account-plus" size={18} color="#fff" />
              <Text style={styles.createBtnText}>Create user</Text>
            </TouchableOpacity>
          </View>
        }
        ListEmptyComponent={
          loading ? null : (
            <View style={styles.emptyWrap}>
              {listError ? (
                <View style={styles.errorCard}>
                  <MaterialCommunityIcons name="alert-circle-outline" size={16} color="#f87171" />
                  <Text style={styles.errorCardText}>{listError}</Text>
                </View>
              ) : (
                <Text style={styles.emptyText}>No accounts found.</Text>
              )}
            </View>
          )
        }
      />

      {!!notice && !createOpen && !resetTarget && (
        <View style={styles.noticeBar} pointerEvents="none">
          <MaterialCommunityIcons name="check-circle-outline" size={16} color="#4ade80" />
          <Text style={styles.noticeText}>{notice}</Text>
        </View>
      )}

      {/* Create-user modal */}
      <Modal
        visible={createOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setCreateOpen(false)}
      >
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
          style={styles.modalBackdrop}
        >
          <TouchableOpacity style={styles.backdropTouch} activeOpacity={1} onPress={() => setCreateOpen(false)} />
          <View style={styles.modalCard}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Create user</Text>
              <TouchableOpacity onPress={() => setCreateOpen(false)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                <MaterialCommunityIcons name="close" size={20} color="#9ca3af" />
              </TouchableOpacity>
            </View>

            <Text style={styles.fieldLabel}>Email</Text>
            <TextInput
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              placeholder="user@sleep.com"
              placeholderTextColor="#444"
              autoCapitalize="none"
              autoComplete="email"
              keyboardType="email-address"
              editable={!creating}
            />

            <Text style={styles.fieldLabel}>Name (optional)</Text>
            <TextInput
              style={styles.input}
              value={name}
              onChangeText={setName}
              placeholder="Display name"
              placeholderTextColor="#444"
              autoCapitalize="words"
              editable={!creating}
            />

            <Text style={styles.fieldLabel}>Password (min {MIN_PASSWORD_LEN} characters)</Text>
            <TextInput
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="••••••••"
              placeholderTextColor="#444"
              secureTextEntry
              autoCapitalize="none"
              editable={!creating}
            />

            <Text style={styles.fieldLabel}>Role</Text>
            <RolePicker value={role} onChange={setRole} disabled={creating} />

            {!!formError && (
              <View style={styles.errorWrap}>
                <MaterialCommunityIcons name="alert-circle-outline" size={14} color="#f87171" />
                <Text style={styles.errorText}>{formError}</Text>
              </View>
            )}

            <View style={styles.modalActions}>
              <TouchableOpacity
                style={[styles.modalBtn, styles.cancelModalBtn, creating && styles.btnDisabled]}
                onPress={() => setCreateOpen(false)}
                disabled={creating}
                activeOpacity={0.8}
              >
                <Text style={styles.cancelModalText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modalBtn, styles.submitModalBtn, creating && styles.btnDisabled]}
                onPress={submitCreate}
                disabled={creating}
                activeOpacity={0.8}
              >
                {creating ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text style={styles.submitModalText}>Create</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Reset-password modal */}
      <Modal
        visible={!!resetTarget}
        transparent
        animationType="fade"
        onRequestClose={() => setResetTarget(null)}
      >
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
          style={styles.modalBackdrop}
        >
          <TouchableOpacity style={styles.backdropTouch} activeOpacity={1} onPress={() => setResetTarget(null)} />
          <View style={styles.modalCard}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Reset password</Text>
              <TouchableOpacity onPress={() => setResetTarget(null)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                <MaterialCommunityIcons name="close" size={20} color="#9ca3af" />
              </TouchableOpacity>
            </View>
            <Text style={styles.modalSubtitle} numberOfLines={1}>
              For {resetTarget ? resetTarget.email : ''}
            </Text>

            <Text style={styles.fieldLabel}>New password (min {MIN_PASSWORD_LEN} characters)</Text>
            <TextInput
              style={styles.input}
              value={newPassword}
              onChangeText={setNewPassword}
              placeholder="••••••••"
              placeholderTextColor="#444"
              secureTextEntry
              autoCapitalize="none"
              editable={!resetting}
            />

            {!!resetError && (
              <View style={styles.errorWrap}>
                <MaterialCommunityIcons name="alert-circle-outline" size={14} color="#f87171" />
                <Text style={styles.errorText}>{resetError}</Text>
              </View>
            )}

            <View style={styles.modalActions}>
              <TouchableOpacity
                style={[styles.modalBtn, styles.cancelModalBtn, resetting && styles.btnDisabled]}
                onPress={() => setResetTarget(null)}
                disabled={resetting}
                activeOpacity={0.8}
              >
                <Text style={styles.cancelModalText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modalBtn, styles.submitModalBtn, resetting && styles.btnDisabled]}
                onPress={submitReset}
                disabled={resetting}
                activeOpacity={0.8}
              >
                {resetting ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text style={styles.submitModalText}>Reset</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0a0a0f' },
  list: { padding: 20, paddingBottom: 40 },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  pageTitle:   { fontSize: 22, fontWeight: '700', color: '#e2e8f0' },
  pageSubtitle:{ fontSize: 12, color: '#555', marginTop: 4, letterSpacing: 0.3 },

  createBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#818cf8',
    borderRadius: 10,
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  createBtnText: { color: '#fff', fontSize: 13, fontWeight: '600' },

  card: {
    backgroundColor: '#13131f',
    borderRadius: 12,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    padding: 14,
    marginBottom: 10,
  },
  cardTop:   { flexDirection: 'row', alignItems: 'center', gap: 12 },
  avatar: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: '#13132a',
    borderWidth: 1,
    borderColor: '#2a2a4a',
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarLetter: { fontSize: 17, fontWeight: '700', color: '#818cf8' },
  identity:     { flex: 1, gap: 3 },
  name:         { fontSize: 15, fontWeight: '600', color: '#fff' },
  email:        { fontSize: 12, color: '#9ca3af' },
  metaRow:      { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 3, flexWrap: 'wrap' },
  roleBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#13132a',
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#2a2a4a',
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  roleBadgeText: { fontSize: 10, fontWeight: '600', letterSpacing: 0.3 },
  created:       { fontSize: 10, color: '#555' },
  resetBtn:      { padding: 6 },

  errorWrap:  { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 12 },
  errorText:  { color: '#f87171', fontSize: 13, flex: 1 },
  emptyWrap:  { alignItems: 'center', paddingVertical: 24 },
  emptyText:  { color: '#555', fontSize: 13 },
  errorCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#13131f',
    borderRadius: 12,
    borderWidth: 0.5,
    borderColor: '#7f1d1d',
    padding: 14,
  },
  errorCardText: { color: '#f87171', fontSize: 13, flex: 1 },

  noticeBar: {
    position: 'absolute',
    left: 20,
    right: 20,
    bottom: 20,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#0a2010',
    borderRadius: 12,
    borderWidth: 0.5,
    borderColor: '#14532d',
    paddingVertical: 10,
    paddingHorizontal: 14,
  },
  noticeText: { color: '#4ade80', fontSize: 13, flex: 1 },

  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.65)' },
  backdropTouch: { flex: 1 },
  modalCard: {
    backgroundColor: '#13131f',
    borderRadius: 16,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    padding: 20,
    marginHorizontal: 20,
    marginBottom: 40,
  },
  modalHeader:   { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  modalTitle:    { fontSize: 17, fontWeight: '700', color: '#fff' },
  modalSubtitle: { fontSize: 12, color: '#9ca3af', marginBottom: 4 },

  fieldLabel: { fontSize: 11, color: '#555', marginTop: 12, marginBottom: 6, letterSpacing: 0.3 },
  input: {
    backgroundColor: '#0a0a0f',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#1a1a2e',
    color: '#e2e8f0',
    fontSize: 15,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },

  roleRow:   { flexDirection: 'row', gap: 8 },
  roleSegment: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    borderWidth: 1,
    borderColor: '#1a1a2e',
    backgroundColor: '#0a0a0f',
    borderRadius: 10,
    paddingVertical: 9,
  },
  roleSegmentSelected: { backgroundColor: '#818cf8', borderColor: '#818cf8' },
  roleLabel:           { color: '#555', fontSize: 13, fontWeight: '500' },
  roleLabelSelected:   { color: '#fff' },

  modalActions: { flexDirection: 'row', gap: 10, marginTop: 18 },
  modalBtn: {
    flex: 1,
    height: 42,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelModalBtn:  { borderWidth: 1, borderColor: '#1a1a2e', backgroundColor: '#0a0a0f' },
  cancelModalText: { color: '#9ca3af', fontSize: 14, fontWeight: '500' },
  submitModalBtn:  { backgroundColor: '#818cf8' },
  submitModalText: { color: '#fff', fontSize: 14, fontWeight: '600' },
  btnDisabled:     { opacity: 0.6 },
});
