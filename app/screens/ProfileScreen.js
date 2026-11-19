import { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { updateProfileName } from '../auth/apiAuth';
import { DISCLAIMER, PROFILE, aboutBulletText } from '../config/displayText';

// Shared identity screen for both roles; the App-info section (patient only) reuses
// DISCLAIMER.about so AboutScreen's wording stays the single source of truth.
export default function ProfileScreen({ user, onLogout, onUserUpdated }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft]     = useState('');
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState('');

  const name  = (user && user.name)  || '';
  const email = (user && user.email) || '';
  const role  = (user && user.role)  || '';
  const roleLabel = Object.hasOwn(PROFILE.roleLabels, role) ? PROFILE.roleLabels[role] : (role || '—');
  const badgeIcon = role === 'doctor' ? 'doctor' : 'account-heart';
  const initial = name.trim().charAt(0).toUpperCase() || email.trim().charAt(0).toUpperCase() || '?';
  const shortId = user && user.id ? `${String(user.id).slice(0, 8)}…` : '—';

  function startEdit() {
    setDraft(name);
    setError('');
    setEditing(true);
  }

  function cancelEdit() {
    setEditing(false);
    setError('');
  }

  async function saveEdit() {
    const next = draft.trim();
    if (!next) {
      setError(PROFILE.errEmptyName);
      return;
    }
    if (next === name.trim()) {
      setEditing(false); // unchanged — nothing to send
      return;
    }

    setError('');
    setSaving(true);
    try {
      const updated = await updateProfileName(next);
      if (!updated) {
        setError(PROFILE.errUnauth); // null → 401 or no stored token; session is gone
        return;
      }
      onUserUpdated(updated);
      setEditing(false);
    } catch (err) {
      setError(err.message || PROFILE.errSaveFailed);
    } finally {
      setSaving(false);
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.sectionRow}>
          <MaterialCommunityIcons name="account-circle" size={22} color="#818cf8" />
          <Text style={styles.sectionTitle}>{PROFILE.sectionAccount}</Text>
        </View>

        <View style={styles.card}>
          <View style={styles.cardTop}>
            <View style={styles.avatar}>
              <Text style={styles.avatarLetter}>{initial}</Text>
            </View>
            <View style={styles.identity}>
              {editing ? (
                <TextInput
                  style={styles.nameInput}
                  value={draft}
                  onChangeText={setDraft}
                  placeholder="Name"
                  placeholderTextColor="#444"
                  autoCapitalize="words"
                  autoFocus
                  returnKeyType="done"
                  editable={!saving}
                  onSubmitEditing={saveEdit}
                />
              ) : (
                <View style={styles.nameRow}>
                  <Text style={styles.name} numberOfLines={1}>{name || '—'}</Text>
                  <TouchableOpacity
                    onPress={startEdit}
                    style={styles.pencilBtn}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                    activeOpacity={0.7}
                  >
                    <MaterialCommunityIcons name="pencil" size={17} color="#818cf8" />
                  </TouchableOpacity>
                </View>
              )}
              <Text style={styles.email} numberOfLines={1}>{email || '—'}</Text>
              <View style={styles.metaRow}>
                <View style={styles.roleBadge}>
                  <MaterialCommunityIcons name={badgeIcon} size={12} color="#818cf8" />
                  <Text style={styles.roleBadgeText}>{roleLabel}</Text>
                </View>
                <Text style={styles.userId} numberOfLines={1}>ID {shortId}</Text>
              </View>
            </View>
          </View>

          {!!error && (
            <View style={styles.errorWrap}>
              <MaterialCommunityIcons name="alert-circle-outline" size={14} color="#f87171" />
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}

          {editing && (
            <View style={styles.editActions}>
              <TouchableOpacity
                style={[styles.editBtn, styles.cancelBtn]}
                onPress={cancelEdit}
                disabled={saving}
                activeOpacity={0.8}
              >
                <Text style={styles.cancelBtnText}>{PROFILE.cancel}</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.editBtn, styles.saveBtn, saving && styles.btnDisabled]}
                onPress={saveEdit}
                disabled={saving}
                activeOpacity={0.8}
              >
                {saving ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text style={styles.saveBtnText}>{PROFILE.save}</Text>
                )}
              </TouchableOpacity>
            </View>
          )}
        </View>

        <TouchableOpacity style={styles.logoutBtn} onPress={onLogout} activeOpacity={0.8}>
          <MaterialCommunityIcons name="logout" size={18} color="#f87171" />
          <Text style={styles.logoutText}>{PROFILE.logout}</Text>
        </TouchableOpacity>

        {role === 'patient' && (
          <>
            <View style={[styles.sectionRow, styles.sectionGap]}>
              <MaterialCommunityIcons name="information-outline" size={22} color="#818cf8" />
              <Text style={styles.sectionTitle}>{PROFILE.sectionAppInfo}</Text>
            </View>
            <View style={styles.infoCard}>
              <Text style={styles.infoTitle}>{DISCLAIMER.about.title}</Text>
              <Text style={styles.infoIntro}>{DISCLAIMER.about.intro}</Text>
              {DISCLAIMER.about.bullets.map((bullet, i) => (
                <View key={i} style={styles.bulletRow}>
                  <Text style={styles.bulletDot}>•</Text>
                  <Text style={styles.bulletText}>{aboutBulletText(bullet)}</Text>
                </View>
              ))}
            </View>
            <View style={styles.closingCard}>
              <MaterialCommunityIcons name="alert-circle-outline" size={16} color="#fbbf24" />
              <Text style={styles.closingText}>{DISCLAIMER.about.closing}</Text>
            </View>
            <Text style={styles.footer}>{DISCLAIMER.footer}</Text>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0a0f' },
  scroll:    { padding: 20, paddingBottom: 40 },

  sectionRow:   { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 14 },
  sectionGap:   { marginTop: 24 },
  sectionTitle: { fontSize: 20, fontWeight: '700', color: '#fff', flex: 1 },

  card: {
    backgroundColor: '#13131f',
    borderRadius: 12,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    padding: 16,
  },
  cardTop:     { flexDirection: 'row', gap: 12 },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#13132a',
    borderWidth: 1,
    borderColor: '#2a2a4a',
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarLetter: { fontSize: 20, fontWeight: '700', color: '#818cf8' },
  identity:     { flex: 1, gap: 5 },
  nameRow:      { flexDirection: 'row', alignItems: 'center', gap: 6 },
  name:         { fontSize: 17, fontWeight: '600', color: '#fff', flexShrink: 1 },
  pencilBtn:    { padding: 2 },
  nameInput: {
    backgroundColor: '#0a0a0f',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#1a1a2e',
    color: '#e2e8f0',
    fontSize: 15,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  email:  { fontSize: 13, color: '#9ca3af' },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 2 },
  roleBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#13132a',
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#2a2a4a',
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  roleBadgeText: { fontSize: 11, fontWeight: '600', color: '#818cf8', letterSpacing: 0.3 },
  userId:        { fontSize: 11, color: '#555', flexShrink: 1 },

  errorWrap: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 12 },
  errorText: { color: '#f87171', fontSize: 13, flex: 1 },

  editActions:   { flexDirection: 'row', gap: 10, marginTop: 14 },
  editBtn: {
    flex: 1,
    height: 42,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelBtn:     { borderWidth: 1, borderColor: '#1a1a2e', backgroundColor: '#0a0a0f' },
  cancelBtnText: { color: '#9ca3af', fontSize: 14, fontWeight: '500' },
  saveBtn:       { backgroundColor: '#818cf8' },
  saveBtnText:   { color: '#fff', fontSize: 14, fontWeight: '600' },
  btnDisabled:   { opacity: 0.6 },

  logoutBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#13131f',
    borderRadius: 12,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    height: 48,
    marginTop: 16,
  },
  logoutText: { color: '#f87171', fontSize: 15, fontWeight: '600' },

  infoCard: {
    backgroundColor: '#13131f',
    borderRadius: 12,
    borderWidth: 0.5,
    borderColor: '#1e1e30',
    padding: 16,
    gap: 10,
  },
  infoTitle:  { fontSize: 15, fontWeight: '600', color: '#e2e8f0' },
  infoIntro:  { fontSize: 12, color: '#9ca3af', lineHeight: 18 },
  bulletRow:  { flexDirection: 'row', gap: 6 },
  bulletDot:  { fontSize: 13, color: '#818cf8', lineHeight: 19 },
  bulletText: { fontSize: 12, color: '#9ca3af', lineHeight: 19, flex: 1 },
  closingCard: {
    backgroundColor: '#2d1f07',
    borderRadius: 12,
    padding: 14,
    marginTop: 12,
    borderWidth: 1,
    borderColor: '#78350f',
    flexDirection: 'row',
    gap: 8,
    alignItems: 'flex-start',
  },
  closingText: { fontSize: 12, color: '#fbbf24', lineHeight: 18, flex: 1 },
  footer:      { fontSize: 10, color: '#4b5563', textAlign: 'center', lineHeight: 15, marginTop: 10 },
});
