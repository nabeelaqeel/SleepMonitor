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
const VERIFY_TIMEOUT_MS = 5000; // session cross-check at restore; best-effort

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
/** True only for complete dotted-quad IPv4 addresses inside the dev LAN
 *  blocklist (10/8, 192.168/16, 172.16/12). Prefix regexes on a hostname
 *  would let strings like "10.evil.com" masquerade as a LAN address. */
function isPrivateIpv4(host) {
  if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(host)) return false; // whole address only
  const octets = host.split('.').map(Number);
  if (octets.some(o => o > 255)) return false;
  const [a, b] = octets;
  return a === 10 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31);
}

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
    isPrivateIpv4(host);
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

  // Bound the whole exchange — headers AND body — to LOGIN_TIMEOUT_MS: the
  // timer stays armed until parsing completes (or fails), so a stalled
  // response can never hang the flow past the timeout.
  const controller = new AbortController();
  const abortTimer = setTimeout(() => controller.abort(), LOGIN_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      signal: controller.signal,
    });

    if (res.status === 401) return null;
    if (!res.ok) throw new Error(`Login server error (HTTP ${res.status})`);

    const { user, token } = await res.json();
    await secureStoreToken(token);
    return user; // {id, email, name, role} — never contains a password
  } catch (err) {
    if (err && err.name === 'AbortError') {
      throw new Error(
        `Login server did not respond within ${LOGIN_TIMEOUT_MS / 1000}s (${API_URL}).`
      );
    }
    if (err instanceof TypeError) {
      // fetch's own network failure (DNS / refused / transport)
      throw new Error(`Cannot reach the login server (${API_URL}). Is the API running?`);
    }
    throw err; // our own status/parse errors — LoginScreen shows their message
  } finally {
    // Settles on EVERY path: success, 401, HTTP error, timeout, parse failure.
    clearTimeout(abortTimer);
  }
}

export async function logout() {
  await AsyncStorage.removeItem(STORAGE_KEY);
  await secureDeleteToken();
}

/** Local-only session validation: user present AND token unexpired.
 *  Clears the stored pair on anything stale and returns null. */
export async function checkSession() {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    const user = raw ? JSON.parse(raw) : null;
    const token = await getStoredToken();
    const payload = decodeTokenPayload(token);
    const tokenUsable = Boolean(payload) && payload.exp * 1000 > Date.now();

    if (user && tokenUsable) return user;
  } catch {
    // fall through — anything corrupt counts as stale
  }
  await AsyncStorage.removeItem(STORAGE_KEY);
  await secureDeleteToken();
  return null;
}

/** Cross-check the restored session against the API's /auth/verify when the
 *  API is reachable: 'valid' (sub+role match the stored user), 'invalid'
 *  (401 or identity mismatch — caller clears), or 'unreachable' (kept, so
 *  offline restore still works — the API is only sometimes up on the LAN). */
async function serverVerify(user, token) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), VERIFY_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_URL}/auth/verify`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    });
    if (res.status === 401) return 'invalid';
    if (!res.ok) return 'unreachable'; // 5xx is not a credential verdict
    const claims = await res.json();
    if (claims && claims.sub === user.id && claims.role === user.role) return 'valid';
    return 'invalid';
  } catch {
    return 'unreachable'; // network error or verify timeout — not a rejection
  } finally {
    clearTimeout(timer);
  }
}

export async function getStoredUser() {
  const user = await checkSession();
  if (!user) return null;

  const token = await getStoredToken();
  const verdict = await serverVerify(user, token);
  if (verdict === 'valid') return user;
  if (verdict === 'invalid') {
    await AsyncStorage.removeItem(STORAGE_KEY);
    await secureDeleteToken();
    return null;
  }
  // 'unreachable': the locally-validated session stands until the next login
  return user;
}

/** Re-validates the session every `intervalMs` while authenticated: when the
 *  JWT's `exp` passes, the stored pair is cleared and `onSessionEnd` fires so
 *  the UI can drop to the login screen. Returns a stop() handle. */
export function startSessionWatch(onSessionEnd, intervalMs = 60000) {
  const handle = setInterval(async () => {
    const user = await checkSession();
    if (!user) {
      clearInterval(handle);
      onSessionEnd && onSessionEnd();
    }
  }, intervalMs);
  return () => clearInterval(handle);
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
