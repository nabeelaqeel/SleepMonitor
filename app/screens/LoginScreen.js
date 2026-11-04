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
} from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { login, storeUser } from '../auth/apiAuth';

export default function LoginScreen({ onLoginSuccess }) {
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [error, setError]       = useState('');
  const [loading, setLoading]   = useState(false);
  const [showPass, setShowPass] = useState(false);

  async function handleLogin() {
    setError('');
    setLoading(true);

    try {
      // Real login: POST /auth/login against the FastAPI service (api/).
      // Resolves with the DB user, null for bad credentials, throws on
      // network/server errors.
      const user = await login(email, password);

      if (!user) {
        setError('Invalid email or password');
        return;
      }

      await storeUser(user);
      onLoginSuccess(user);
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  }

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
        <Text style={styles.cardTitle}>Sign In</Text>

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
              placeholder="••••••••"
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

        {/* Error */}
        {!!error && (
          <View style={styles.errorWrap}>
            <MaterialCommunityIcons name="alert-circle-outline" size={14} color="#f87171" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        )}

        {/* Login button */}
        <TouchableOpacity
          style={[styles.button, loading && styles.buttonDisabled]}
          onPress={handleLogin}
          disabled={loading}
          activeOpacity={0.8}
        >
          {loading ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <Text style={styles.buttonText}>Sign In</Text>
          )}
        </TouchableOpacity>
      </View>

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

  // Header
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

  // Card
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

  // Input
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

  // Error
  errorWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 16,
  },
  errorText: {
    color: '#f87171',
    fontSize: 13,
  },

  // Button
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

  // Footer
  footer: {
    marginTop: 32,
    fontSize: 11,
    color: '#2a2a4a',
    letterSpacing: 0.3,
  },
});
