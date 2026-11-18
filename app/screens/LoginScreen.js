import { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  Modal,
} from 'react-native';
import * as WebBrowser from 'expo-web-browser';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { login, registerAccount, storeUser } from '../auth/apiAuth';
import { useGoogleSignIn } from '../auth/googleAuth';

// Web OAuth popups need this to close themselves; no-op on native.
if (Platform.OS === 'web') WebBrowser.maybeCompleteAuthSession();

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD_LEN = 8;

const ROLES = [
  { value: 'doctor', label: 'Doctor', icon: 'doctor' },
  { value: 'patient', label: 'Patient', icon: 'account-heart' },
];

function RolePicker({ value, onChange, disabled }) {
  return (
    <View style={styles.roleRow}>
      {ROLES.map(role => {
        const selected = value === role.value;
        return (
          <TouchableOpacity
            key={role.value}
            style={[styles.roleSegment, selected && styles.roleSegmentSelected, disabled && styles.disabled]}
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

export default function LoginScreen({ onLoginSuccess }) {
  const [mode, setMode] = useState('signin'); // 'signin' | 'register'
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm]   = useState('');
  const [role, setRole]         = useState('patient');
  const [error, setError]       = useState('');
  const [loading, setLoading]   = useState(false);
  const [showPass, setShowPass] = useState(false);

  const google = useGoogleSignIn({
    onSession: user => onLoginSuccess(user),
    onError: message => setError(message),
  });

  async function finishLogin(user) {
    await storeUser(user);
    onLoginSuccess(user);
  }

  async function handleLogin() {
    setError('');
    setLoading(true);

    try {
      // Real login: POST /auth/login (api/). Resolves with the DB user, null for bad credentials; throws otherwise.
      const user = await login(email, password);

      if (!user) {
        setError('Invalid email or password');
        return;
      }

      await finishLogin(user);
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister() {
    setError('');

    if (!EMAIL_PATTERN.test(email.trim())) {
      setError('Enter a valid email address');
      return;
    }
    if (password.length < MIN_PASSWORD_LEN) {
      setError(`Password must be at least ${MIN_PASSWORD_LEN} characters`);
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match');
      return;
    }

    setLoading(true);
    try {
      const user = await registerAccount({ email, password, role });
      await finishLogin(user);
    } catch (err) {
      setError(err.message || 'Registration failed');
    } finally {
      setLoading(false);
    }
  }

  function switchMode(next) {
    if (mode === next) return;
    setMode(next);
    setError('');
  }

  function busy() {
    return loading || google.loading;
  }

  const isRegister = mode === 'register';
  const googleHint = !google.googleConfigured
    ? 'Google sign-in is not configured for this build — email sign-in only.'
    : google.unavailable
      ? 'Google sign-in unavailable on this server — email sign-in only.'
      : null;

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      {/* ── Header ── */}
      <View style={styles.header}>
        <View style={styles.iconWrap}>
          <MaterialCommunityIcons name="sleep" size={40} color="#818cf8" />
        </View>
        <Text style={styles.title}>Sleep Monitor</Text>
        <Text style={styles.subtitle}>QoS-Aware Sleep Monitoring System</Text>
      </View>

      {/* ── Card ── */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>{isRegister ? 'Create Account' : 'Sign In'}</Text>

        {/* Email */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Email</Text>
          <View style={styles.inputWrap}>
            <MaterialCommunityIcons
              name="email-outline"
              size={18}
              color="#555"
              style={styles.inputIcon}
            />
            <TextInput
              style={styles.input}
              placeholder="you@example.com"
              placeholderTextColor="#444"
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              value={email}
              onChangeText={setEmail}
            />
          </View>
        </View>

        {/* Password */}
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Password</Text>
          <View style={styles.inputWrap}>
            <MaterialCommunityIcons
              name="lock-outline"
              size={18}
              color="#555"
              style={styles.inputIcon}
            />
            <TextInput
              style={[styles.input, { flex: 1 }]}
              placeholder={isRegister ? 'At least 8 characters' : '••••••••'}
              placeholderTextColor="#444"
              secureTextEntry={!showPass}
              autoCapitalize="none"
              value={password}
              onChangeText={setPassword}
            />
            <TouchableOpacity
              onPress={() => setShowPass(v => !v)}
              style={styles.eyeBtn}
            >
              <MaterialCommunityIcons
                name={showPass ? 'eye-off-outline' : 'eye-outline'}
                size={18}
                color="#555"
              />
            </TouchableOpacity>
          </View>
        </View>

        {/* Confirm + role (register only) */}
        {isRegister && (
          <>
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Confirm Password</Text>
              <View style={styles.inputWrap}>
                <MaterialCommunityIcons
                  name="lock-check-outline"
                  size={18}
                  color="#555"
                  style={styles.inputIcon}
                />
                <TextInput
                  style={styles.input}
                  placeholder="Repeat password"
                  placeholderTextColor="#444"
                  secureTextEntry={!showPass}
                  autoCapitalize="none"
                  value={confirm}
                  onChangeText={setConfirm}
                />
              </View>
            </View>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>I am a</Text>
              <RolePicker value={role} onChange={setRole} disabled={busy()} />
            </View>
          </>
        )}

        {/* Error */}
        {!!error && (
          <View style={styles.errorWrap}>
            <MaterialCommunityIcons name="alert-circle-outline" size={14} color="#f87171" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        )}

        {/* Primary button */}
        <TouchableOpacity
          style={[styles.button, busy() && styles.buttonDisabled]}
          onPress={isRegister ? handleRegister : handleLogin}
          disabled={busy()}
          activeOpacity={0.8}
        >
          {busy() ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <Text style={styles.buttonText}>{isRegister ? 'Create Account' : 'Sign In'}</Text>
          )}
        </TouchableOpacity>

        {/* Google (sign-in mode only) */}
        {!isRegister && (
          <>
            <View style={styles.divider}>
              <View style={styles.dividerLine} />
              <Text style={styles.dividerText}>or</Text>
              <View style={styles.dividerLine} />
            </View>
            <TouchableOpacity
              style={[styles.googleButton, (busy() || google.unavailable) && styles.buttonDisabled]}
              onPress={google.prompt}
              disabled={busy() || google.unavailable}
              activeOpacity={0.8}
            >
              <MaterialCommunityIcons name="google" size={18} color="#e2e8f0" />
              <Text style={styles.googleButtonText}>Continue with Google</Text>
            </TouchableOpacity>
            {googleHint && (
              <Text style={styles.googleHint}>{googleHint}</Text>
            )}
          </>
        )}
      </View>

      {/* ── Mode toggle ── */}
      {isRegister ? (
        <Text style={styles.modeToggle}>
          Already registered?{' '}
          <Text style={styles.modeToggleLink} onPress={() => switchMode('signin')}>
            Sign in
          </Text>
        </Text>
      ) : (
        <Text style={styles.modeToggle}>
          New user?{' '}
          <Text style={styles.modeToggleLink} onPress={() => switchMode('register')}>
            Create an account
          </Text>
        </Text>
      )}

      {/* ── First-login role choice (Google accounts) ── */}
      <Modal
        visible={google.needsRole}
        transparent
        animationType="fade"
        onRequestClose={google.cancelRole}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <MaterialCommunityIcons name="account-question-outline" size={36} color="#818cf8" />
            <Text style={styles.modalTitle}>Choose your role</Text>
            <Text style={styles.modalBody}>
              Your Google account has no Sleep Monitor profile yet. Pick how you'll use the app.
            </Text>
            <RolePicker value={role} onChange={setRole} disabled={google.loading} />
            <TouchableOpacity
              style={[styles.button, google.loading && styles.buttonDisabled]}
              onPress={() => google.chooseRole(role)}
              disabled={google.loading}
              activeOpacity={0.8}
            >
              {google.loading ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Text style={styles.buttonText}>Continue</Text>
              )}
            </TouchableOpacity>
            <TouchableOpacity
              onPress={google.cancelRole}
              disabled={google.loading}
              style={styles.modalCancel}
            >
              <Text style={styles.modalCancelText}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* ── Footer ── */}
      <Text style={styles.footer}>
        Monitoring powered by QoS-aware MQTT
      </Text>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#0a0a0f',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },

  header: {
    alignItems: 'center',
    marginBottom: 36,
  },
  iconWrap: {
    width: 72,
    height: 72,
    borderRadius: 20,
    backgroundColor: '#13132a',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#2a2a4a',
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#ffffff',
    letterSpacing: 0.5,
  },
  subtitle: {
    fontSize: 13,
    color: '#555',
    marginTop: 6,
    letterSpacing: 0.3,
  },

  card: {
    width: '100%',
    backgroundColor: '#0f0f1a',
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#1a1a2e',
    padding: 24,
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#e2e8f0',
    marginBottom: 24,
  },

  inputGroup: {
    marginBottom: 16,
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
  eyeBtn: {
    padding: 4,
  },

  roleRow: {
    flexDirection: 'row',
    gap: 8,
  },
  roleSegment: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    height: 44,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#1a1a2e',
    backgroundColor: '#0a0a0f',
  },
  roleSegmentSelected: {
    backgroundColor: '#818cf8',
    borderColor: '#818cf8',
  },
  roleLabel: {
    fontSize: 14,
    color: '#888',
    fontWeight: '500',
  },
  roleLabelSelected: {
    color: '#fff',
  },

  errorWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 16,
  },
  errorText: {
    color: '#f87171',
    fontSize: 13,
    flex: 1,
  },

  button: {
    backgroundColor: '#818cf8',
    borderRadius: 12,
    height: 50,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 8,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
    letterSpacing: 0.3,
  },

  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginTop: 20,
    marginBottom: 16,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: '#1a1a2e',
  },
  dividerText: {
    fontSize: 12,
    color: '#555',
  },

  googleButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#13132a',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#2a2a4a',
    height: 48,
  },
  googleButtonText: {
    color: '#e2e8f0',
    fontSize: 15,
    fontWeight: '500',
  },
  googleHint: {
    fontSize: 12,
    color: '#555',
    textAlign: 'center',
    marginTop: 10,
    lineHeight: 17,
  },

  modeToggle: {
    marginTop: 24,
    fontSize: 13,
    color: '#555',
  },
  modeToggleLink: {
    color: '#818cf8',
    fontWeight: '600',
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
    fontSize: 18,
    fontWeight: '600',
    color: '#e2e8f0',
    marginTop: 12,
  },
  modalBody: {
    fontSize: 13,
    color: '#888',
    textAlign: 'center',
    marginTop: 8,
    marginBottom: 20,
    lineHeight: 19,
  },
  modalCancel: {
    marginTop: 12,
    padding: 8,
  },
  modalCancelText: {
    color: '#555',
    fontSize: 14,
  },

  footer: {
    marginTop: 32,
    fontSize: 11,
    color: '#2a2a4a',
    letterSpacing: 0.3,
  },
});
