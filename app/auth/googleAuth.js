// Google sign-in: native Play-Services sign-in (@react-native-google-signin/
// google-signin) — no browser involved. The previous expo-auth-session
// browser flow could never work on Android: Google rejects custom-scheme
// redirects for WEB-type clients (Error 400: invalid_request) and ANDROID-type
// clients have no browser flow at all. The native flow returns an id_token
// whose `aud` is the WEB client id, handed to POST /auth/google where the API
// verifies it against its GOOGLE_CLIENT_ID — server contract unchanged.
// The app only ever handles public client IDs — no client secret lives here.

import { useState, useRef } from 'react';
import { Platform } from 'react-native';
import Constants from 'expo-constants';
import {
  GoogleSignin,
  isErrorWithCode,
  isSuccessResponse,
  statusCodes,
} from '@react-native-google-signin/google-signin';
import { API_URL, GOOGLE_CLIENT_ID, GOOGLE_CONFIGURED } from '../config/appConfig';
import { secureStoreToken } from './apiAuth';

const GOOGLE_TIMEOUT_MS = 15000;

// The native Google module is absent in Expo Go — the screen shows that
// up front instead.
export const RUNNING_IN_EXPO_GO =
  Constants.executionEnvironment === 'storeClient' || Constants.appOwnership === 'expo';

/** POST /auth/google — { user } (token stored), { needsRole } (re-post the SAME
 *  id_token with a role) or { unavailable } (server lacks GOOGLE_CLIENT_ID);
 *  401 throws a displayable error. */
export async function googleSignIn(idToken, role) {
  const controller = new AbortController();
  const abortTimer = setTimeout(() => controller.abort(), GOOGLE_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_URL}/auth/google`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // The role only rides along on the second post, after needs_role.
      body: JSON.stringify(role ? { id_token: idToken, role } : { id_token: idToken }),
      signal: controller.signal,
    });

    if (res.status === 401) throw new Error('Invalid or expired Google token');
    if (res.status === 503) return { unavailable: true };
    if (!res.ok) throw new Error(`Google sign-in server error (HTTP ${res.status})`);

    const body = await res.json();
    if (body && body.needs_role) return { needsRole: true };
    if (!body || !body.user || !body.token) {
      throw new Error('Google sign-in returned an unexpected response');
    }
    await secureStoreToken(body.token);
    return { user: body.user };
  } catch (err) {
    if (err && err.name === 'AbortError') {
      throw new Error(
        `Google sign-in server did not respond within ${GOOGLE_TIMEOUT_MS / 1000}s (${API_URL}).`
      );
    }
    if (err instanceof TypeError) {
      throw new Error(`Cannot reach the Google sign-in server (${API_URL}). Is the API running?`);
    }
    throw err;
  } finally {
    clearTimeout(abortTimer);
  }
}

/** Native Google errors → displayable message; null = stay silent (user backed
 *  out, or a flow is already running). Code '10' is Play-Services DEVELOPER_ERROR:
 *  the APK's package + signing SHA-1 is not registered in Google Cloud Console. */
function describeGoogleError(err) {
  if (!isErrorWithCode(err)) return (err && err.message) || 'Google sign-in failed';
  switch (err.code) {
    case statusCodes.SIGN_IN_CANCELLED:
    case statusCodes.IN_PROGRESS:
      return null;
    case statusCodes.PLAY_SERVICES_NOT_AVAILABLE:
      return 'Google Play Services is missing or outdated on this device — Google sign-in needs it.';
    case '10':
      return 'Google rejected this app: its package name + signing SHA-1 is not registered in the Google Cloud Console yet.';
    default:
      return err.message || 'Google sign-in failed';
  }
}

/** Native Play-Services sign-in + /auth/google handoff for the login screen. */
export function useGoogleSignIn({ onSession, onError }) {
  const [needsRole, setNeedsRole] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(false);
  const pendingTokenRef = useRef(null);

  /** Server handoff for a verified id_token (needs-role flow included). */
  async function handleIdToken(idToken) {
    setLoading(true);
    try {
      const result = await googleSignIn(idToken);
      if (result.unavailable) setUnavailable(true);
      else if (result.needsRole) {
        pendingTokenRef.current = idToken;
        setNeedsRole(true);
      } else {
        onSession(result.user);
      }
    } catch (err) {
      onError(err.message || 'Google sign-in failed');
    } finally {
      setLoading(false);
    }
  }

  /** First-login role choice — re-posts the SAME id_token with role attached. */
  async function chooseRole(role) {
    const idToken = pendingTokenRef.current;
    if (!idToken) return;
    setLoading(true);
    try {
      const result = await googleSignIn(idToken, role);
      setNeedsRole(false);
      pendingTokenRef.current = null;
      if (result.unavailable) setUnavailable(true);
      else if (result.needsRole) onError('The server still requested a role — please try again.');
      else onSession(result.user);
    } catch (err) {
      setNeedsRole(false);
      pendingTokenRef.current = null;
      onError(err.message || 'Google sign-in failed');
    } finally {
      setLoading(false);
    }
  }

  function cancelRole() {
    pendingTokenRef.current = null;
    setNeedsRole(false);
  }

  async function prompt() {
    setUnavailable(false);
    if (RUNNING_IN_EXPO_GO) {
      onError(
        'Google sign-in needs a development build or the release APK — Expo Go cannot ' +
        'load the native Google module.'
      );
      return;
    }
    if (Platform.OS === 'web') {
      onError('Google sign-in runs on the Android/iOS app only — the web build supports email sign-in.');
      return;
    }
    if (!GOOGLE_CONFIGURED) return;
    try {
      // webClientId is the WEB-type console client — the id_token Google
      // returns carries it as `aud`, which is what the API expects.
      GoogleSignin.configure({ webClientId: GOOGLE_CLIENT_ID });
      await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
      const response = await GoogleSignin.signIn();
      if (!isSuccessResponse(response)) return; // user closed the account sheet
      const idToken = response.data && response.data.idToken;
      if (!idToken) {
        onError("Google returned no ID token — this build's webClientId is missing or invalid.");
        return;
      }
      await handleIdToken(idToken);
    } catch (err) {
      const message = describeGoogleError(err);
      if (message) onError(message);
    }
  }

  return { prompt, needsRole, unavailable, loading, googleConfigured: GOOGLE_CONFIGURED, runningInExpoGo: RUNNING_IN_EXPO_GO, chooseRole, cancelRole };
}
