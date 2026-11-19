// Database-backed auth via the FastAPI service in api/ (bcrypt + short-lived
// HS256 JWT). Storage/transport rules: docs/AUTH_API.md. The API base URL is
// build-time config (app.config.js `extra` / EXPO_PUBLIC_API_URL — see
// app/config/appConfig.js) so release builds can bake a different endpoint.

import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { API_URL } from '../config/appConfig';

const STORAGE_KEY = 'current_user';
const TOKEN_KEY   = 'auth_token';

const LOGIN_TIMEOUT_MS = 15000; // a hung server must not freeze the login button
const VERIFY_TIMEOUT_MS = 5000; // session cross-check at restore; best-effort

const secureGetToken = () =>
  Platform.OS === 'web' ? AsyncStorage.getItem(TOKEN_KEY) : SecureStore.getItemAsync(TOKEN_KEY);
export const secureStoreToken = token =>
  Platform.OS === 'web' ? AsyncStorage.setItem(TOKEN_KEY, token) : SecureStore.setItemAsync(TOKEN_KEY, token);
const secureDeleteToken = () =>
  Platform.OS === 'web' ? AsyncStorage.removeItem(TOKEN_KEY) : SecureStore.deleteItemAsync(TOKEN_KEY);

/** Client-side JWT decode — the signature is only checkable server-side; a stale/absent exp never restores a session. */
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

/** True only for a complete dotted-quad IPv4 in the dev LAN blocklist — prefix
 *  regexes would let "10.evil.com" masquerade as a LAN address. */
function isPrivateIpv4(host) {
  if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(host)) return false; // whole address only
  const octets = host.split('.').map(Number);
  if (octets.some(o => o > 255)) return false;
  const [a, b] = octets;
  return a === 10 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31);
}

/** Transport guard before login and each verify: default-deny for plain HTTP
 *  outside loopback/dev-LAN; escapes are HTTPS/LAN as-is or
 *  EXPO_PUBLIC_ALLOW_PLAIN_HTTP=true (flagged demo tradeoff). */
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
  const plainHttpAllowedByFlag =
    process.env.EXPO_PUBLIC_ALLOW_PLAIN_HTTP === 'true';
  if (url.protocol === 'http:' && !loopbackOrLan && !plainHttpAllowedByFlag) {
    throw new Error(
      `Refusing to send credentials over plain HTTP to '${host}'. ` +
      'Use an HTTPS endpoint, point EXPO_PUBLIC_API_URL at a private LAN ' +
      'address, or set EXPO_PUBLIC_ALLOW_PLAIN_HTTP=true to accept the ' +
      'demo tradeoff explicitly.'
    );
  }
}

/** Returns the user, or null for bad credentials; network failures throw so the
 *  screen can show a distinct, honest message. */
export async function login(email, password) {
  assertSecureEndpoint();

  // Timer stays armed until parsing completes, so a stalled response can't hang past LOGIN_TIMEOUT_MS.
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

/** Pydantic 422 bodies carry an array of {msg, loc} objects; anything else may
 *  be a plain string — flatten to one screen-displayable sentence. */
function describeValidationError(detail, fallback = 'Registration rejected') {
  if (Array.isArray(detail)) {
    const first = detail[0];
    if (first && typeof first.msg === 'string') {
      const where = Array.isArray(first.loc)
        ? first.loc.filter(part => part !== 'body').join('.')
        : '';
      return where ? `Validation error: ${first.msg} (${where})` : `Validation error: ${first.msg}`;
    }
  }
  if (typeof detail === 'string' && detail) return detail;
  return fallback;
}

/** POST /auth/register — returns the user; 409/422 surface as thrown errors so
 *  the screen can show a distinct message per failure kind. */
export async function registerAccount({ email, password, role }) {
  assertSecureEndpoint();

  const controller = new AbortController();
  const abortTimer = setTimeout(() => controller.abort(), LOGIN_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase(), password, role }),
      signal: controller.signal,
    });

    if (res.status === 409) throw new Error('Email already registered');
    if (res.status === 422) {
      let detail = null;
      try { ({ detail } = await res.json()); } catch { /* empty body falls through */ }
      throw new Error(describeValidationError(detail, 'Registration rejected'));
    }
    if (!res.ok) throw new Error(`Registration server error (HTTP ${res.status})`);

    const { user, token } = await res.json();
    await secureStoreToken(token);
    return user;
  } catch (err) {
    if (err && err.name === 'AbortError') {
      throw new Error(
        `Registration server did not respond within ${LOGIN_TIMEOUT_MS / 1000}s (${API_URL}).`
      );
    }
    if (err instanceof TypeError) {
      throw new Error(`Cannot reach the registration server (${API_URL}). Is the API running?`);
    }
    throw err;
  } finally {
    clearTimeout(abortTimer);
  }
}

/** PATCH /auth/me — updates the signed-in user's display name. Returns the
 *  updated user, or null when the session is invalid/expired (401 or no stored
 *  token); 422 and network failures throw so the screen can show a message. */
export async function updateProfileName(newName) {
  assertSecureEndpoint();
  const token = await getStoredToken();
  if (!token) return null; // same verdict as a 401 — no session to update

  const controller = new AbortController();
  const abortTimer = setTimeout(() => controller.abort(), LOGIN_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_URL}/auth/me`, {
      method: 'PATCH',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ name: newName.trim() }),
      signal: controller.signal,
    });

    if (res.status === 401) return null;
    if (res.status === 422) {
      let detail = null;
      try { ({ detail } = await res.json()); } catch { /* empty body falls through */ }
      throw new Error(describeValidationError(detail, 'Name update rejected'));
    }
    if (!res.ok) throw new Error(`Name update server error (HTTP ${res.status})`);

    const { user } = await res.json();
    // Persisted here (not in the screen) so the next launch shows the new name on every path.
    await storeUser(user);
    return user;
  } catch (err) {
    if (err && err.name === 'AbortError') {
      throw new Error(
        `Profile server did not respond within ${LOGIN_TIMEOUT_MS / 1000}s (${API_URL}).`
      );
    }
    if (err instanceof TypeError) {
      throw new Error(`Cannot reach the server (${API_URL}). Is the API running?`);
    }
    throw err;
  } finally {
    clearTimeout(abortTimer);
  }
}

/** Local-only validation: user present AND token unexpired; clears the stored pair on anything stale. */
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

/** Cross-checks the restored session against /auth/verify: 'valid', 'invalid'
 *  (caller clears), or 'unreachable' (kept — offline restore still works). */
async function serverVerify(user, token) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), VERIFY_TIMEOUT_MS);
  try {
    // Same guard as login(): a guard throw counts as 'unreachable' (session kept locally).
    assertSecureEndpoint();
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

/** Re-validates the session every intervalMs; when the JWT's exp passes, clears
 *  the stored pair and fires onSessionEnd so the UI drops to login. */
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

const DATA_TIMEOUT_MS = 10000; // roster/device payloads are bigger than a verify; still bounded

/** Shared transport for the workflow endpoints (roster, devices, pairing).
 *  Reads the stored session token itself so screens never pass tokens around;
 *  error bodies surface verbatim when they are display strings ("detail"). */
async function authedFetch(path, { method = 'GET', body, fallback } = {}) {
  assertSecureEndpoint();
  const token = await getStoredToken();
  if (!token) throw new Error('Not signed in');

  const controller = new AbortController();
  const abortTimer = setTimeout(() => controller.abort(), DATA_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    if (!res.ok) {
      let detail = null;
      try { ({ detail } = await res.json()); } catch { /* empty body → fallback below */ }
      throw new Error(describeValidationError(detail, fallback || `Server error (HTTP ${res.status})`));
    }
    return res.json();
  } catch (err) {
    if (err && err.name === 'AbortError') {
      throw new Error(`Server did not respond within ${DATA_TIMEOUT_MS / 1000}s (${API_URL}).`);
    }
    if (err instanceof TypeError) {
      throw new Error(`Cannot reach the server (${API_URL}). Is the API running?`);
    }
    throw err;
  } finally {
    clearTimeout(abortTimer);
  }
}

/** GET /patients (doctor) — the linked-patient roster, sorted by name server-side. */
export async function fetchPatients() {
  const body = await authedFetch('/patients', { fallback: 'Could not load patients' });
  return body.patients || [];
}

/** GET /alerts (doctor) — persisted Critical/Important alert history, ts DESC, max 50. */
export async function fetchAlertHistory() {
  const body = await authedFetch('/alerts', { fallback: 'Could not load alert history' });
  return body.alerts || [];
}

/** GET /devices (patient) — bound watches, oldest first. */
export async function fetchDevices() {
  const body = await authedFetch('/devices', { fallback: 'Could not load devices' });
  return body.devices || [];
}

/** POST /devices/bind (patient) — same-patient rebind is a display_name refresh;
 *  omitting displayName keeps the stored one. 409 surfaces verbatim. */
export async function bindDevice(deviceId, displayName) {
  const payload = { device_id: deviceId };
  if (displayName && displayName.trim()) payload.display_name = displayName.trim();
  const body = await authedFetch('/devices/bind', {
    method: 'POST',
    body: payload,
    fallback: 'Could not bind device',
  });
  return body.device;
}

/** GET /auth/pairing-code (doctor) — the code the doctor shares with a patient. */
export async function getPairingCode() {
  const body = await authedFetch('/auth/pairing-code', { fallback: 'Could not fetch pairing code' });
  return body.pairing_code;
}

/** POST /auth/link-doctor (patient) — idempotent; returns the linked doctor. */
export async function linkDoctor(code) {
  return authedFetch('/auth/link-doctor', {
    method: 'POST',
    body: { code },
    fallback: 'Could not link to doctor',
  });
}
