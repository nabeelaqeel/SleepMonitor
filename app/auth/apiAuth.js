// Database-backed authentication. `login()` calls the FastAPI service in
// api/ (host venv), which bcrypt-verifies the password against
// users.password_hash and issues a short-lived HS256 JWT. The JWT is kept
// in its own AsyncStorage key so the stored user shape is identical to
// what mockAuth used to store — App.js needs no changes beyond the import.
//
// Set EXPO_PUBLIC_API_URL in app/.env.development (gitignored) — the API
// binds 0.0.0.0 on this host so devices on the same LAN can reach it.

import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEY = 'current_user';
const TOKEN_KEY   = 'auth_token';

const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://192.168.0.29:8000';

/**
 * Returns the user object on success, or null for bad credentials (the
 * screen shows its existing "Invalid email or password" message). Network
 * failures throw so the screen can display a distinct, honest message.
 */
export async function login(email, password) {
  let res;
  try {
    res = await fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
    });
  } catch {
    throw new Error(`Cannot reach the login server (${API_URL}). Is the API running?`);
  }

  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`Login server error (HTTP ${res.status})`);

  const { user, token } = await res.json();
  await AsyncStorage.setItem(TOKEN_KEY, token);
  return user; // {id, email, name, role} — never contains a password
}

export async function logout() {
  await AsyncStorage.multiRemove([STORAGE_KEY, TOKEN_KEY]);
}

export async function getStoredUser() {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export async function storeUser(user) {
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(user));
}

export async function getStoredToken() {
  return AsyncStorage.getItem(TOKEN_KEY);
}
