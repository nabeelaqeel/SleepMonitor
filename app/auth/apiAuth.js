// Database-backed authentication. `login()` calls the FastAPI service in
// api/ (host venv), which bcrypt-verifies the password against
// users.password_hash and issues a short-lived HS256 JWT.
//
// Storage and transport rules (see docs/AUTH_API.md):
//  * the session user object (non-sensitive: id/email/name/role) lives in
//    AsyncStorage under 'current_user', exactly as before;
//  * the JWT lives in encrypted native storage (expo-secure-store =
//    iOS Keychain / Android Keystore). SecureStore has no web build, so
//    web previews fall back to AsyncStorage — same as the legacy flow;
//  * restoring a session requires BOTH a stored user and an unexpired
//    token; either one missing/stale clears both and forces a re-login;
//  * credentials are never sent to a plain-HTTP endpoint unless it is a
//    loopback/private-LAN address (the documented dev setup). HTTPS hosts
//    are validated by the RN networking stack's certificate checks.
//
// Set EXPO_PUBLIC_API_URL in app/.env.development (gitignored) — the API
// binds 0.0.0.0 on this host so devices on the same LAN can reach it.

import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

const STORAGE_KEY = 'current_user';
const TOKEN_KEY   = 'auth_token';

const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://192.168.0.29:8000';
const LOGIN_TIMEOUT_MS = 15000; // a hung server must not freeze the login button

// ── Token storage: secure native store, AsyncStorage on web ────────────────
const secureGetToken = () =>
  Platform.OS === 'web' ? AsyncStorage.getItem(TOKEN_KEY) : SecureStore.getItemAsync(TOKEN_KEY);
const secureStoreToken = token =>
  Platform.OS === 'web' ? AsyncStorage.setItem(TOKEN_KEY, token) : SecureStore.setItemAsync(TOKEN_KEY, token);
const secureDeleteToken = () =>
  Platform.OS === 'web' ? AsyncStorage.removeItem(TOKEN_KEY) : SecureStore.deleteItemAsync(TOKEN_KEY);

/** Decode the JWT payload client-side; the HS256 signature can only be
 *  checked server-side, but an expired/absent `exp` never restores a
 *  session. Returns the payload object or null. */
function decodeTokenPayload(token) {
  if (typeof token !== 'string' || !token) return null;
  try {
    const b64 = token.split('.')[1]?.replace(/-/g, '+').replace(/_/g, '/');
    if (!b64) return null;
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    const payload = JSON.parse(atob(padded));
    return Number.isFinite(payload.exp) ? payload : null;
  } catch {
    return null;
  }
}

// ── Endpoint transport guard ────────────────────────────────────────────────
function assertSecureEndpoint() {
  let url;
  try {
    url = new URL(API_URL);
  } catch {
    throw new Error(`Invalid EXPO_PUBLIC_API_URL: '${API_URL}'`);
  }
  const host = url.hostname;
  const loopbackOrLan =
    host === 'localhost' || host === '127.0.0.1' || host.endsWith('.local') ||
    /^10\./.test(host) || /^192\.168\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host);
  if (url.protocol === 'http:' && !loopbackOrLan) {
    throw new Error(
      `Refusing to send credentials over plain HTTP to '${host}'. ` +
      'Use an HTTPS endpoint, or point EXPO_PUBLIC_API_URL at a private LAN address.'
    );
  }
}

// ── Auth actions ────────────────────────────────────────────────────────────
/**
 * Returns the user object on success, or null for bad credentials (the
 * screen shows its existing "Invalid email or password" message). Network
 * failures throw so the screen can display a distinct, honest message.
 */
export async function login(email, password) {
  assertSecureEndpoint();

  // Bound the attempt: AbortController + timeout so a hung server surfaces
  // as a catchable error (LoginScreen re-enables the button) instead of a
  // forever-spinning fetch.
  const controller = new AbortController();
  const abortTimer = setTimeout(() => controller.abort(), LOGIN_TIMEOUT_MS);

  let res;
  try {
    res = await fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      signal: controller.signal,
    });
  } catch (err) {
    if (err && err.name === 'AbortError') {
      throw new Error(
        `Login server did not respond within ${LOGIN_TIMEOUT_MS / 1000}s (${API_URL}).`
      );
    }
    throw new Error(`Cannot reach the login server (${API_URL}). Is the API running?`);
  } finally {
    clearTimeout(abortTimer);
  }

  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`Login server error (HTTP ${res.status})`);

  const { user, token } = await res.json();
  await secureStoreToken(token);
  return user; // {id, email, name, role} — never contains a password
}

export async function logout() {
  await AsyncStorage.removeItem(STORAGE_KEY);
  await secureDeleteToken();
}

export async function getStoredUser() {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    const user = raw ? JSON.parse(raw) : null;
    const token = await secureGetToken();
    const payload = decodeTokenPayload(token);
    const tokenUsable = Boolean(payload) && payload.exp * 1000 > Date.now();

    if (user && tokenUsable) return user;

    // Anything stale (no token, expired token, corrupt user) forces a clean
    // re-login instead of restoring a half-session.
    await AsyncStorage.removeItem(STORAGE_KEY);
    await secureDeleteToken();
    return null;
  } catch {
    return null;
  }
}

export async function storeUser(user) {
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(user));
}

export async function getStoredToken() {
  try {
    return await secureGetToken();
  } catch {
    return null;
  }
}
