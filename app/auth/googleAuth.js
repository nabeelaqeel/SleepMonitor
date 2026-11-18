// Google sign-in: expo-auth-session fetches an id_token, which is handed to
// POST /auth/google where the API verifies it against its GOOGLE_CLIENT_ID.
// The app only ever handles public client IDs — no client secret lives here.

import { useEffect, useRef, useState } from 'react';
import Constants from 'expo-constants';
// expo-auth-session 7.x no longer exports the Google provider from its main
// entry, and the shim file is lowercase — Linux resolution is case-sensitive.
import { ResponseType } from 'expo-auth-session';
import { useIdTokenAuthRequest } from 'expo-auth-session/providers/google';
import { API_URL, GOOGLE_CLIENT_ID, GOOGLE_CONFIGURED } from '../config/appConfig';
import { secureStoreToken } from './apiAuth';

const GOOGLE_TIMEOUT_MS = 15000;

// The SDK's redirect scheme is makeRedirectUri()-based (expo-auth-session 7.x
// has no auth proxy left), which needs a real app scheme — Expo Go cannot
// complete Google OAuth, so the screen shows that up front instead.
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

/** OAuth hook + /auth/google handoff for the login screen. */
export function useGoogleSignIn({ onSession, onError }) {
  const [needsRole, setNeedsRole] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(false);
  const pendingTokenRef = useRef(null);

  // Implicit id_token flow for every platform (no client secret exists here —
  // a code exchange against a Web client would require one server-side).
  const [, response, promptAsync] = useIdTokenAuthRequest(
    {
      clientId: GOOGLE_CLIENT_ID || 'not-configured',
      responseType: ResponseType.IdToken,
      scopes: ['openid', 'email', 'profile'],
    },
    {}
  );

  useEffect(() => {
    if (!response) return undefined;
    if (response.type !== 'success') {
      if (response.type === 'error') {
        onError('Google sign-in failed: ' + ((response.error && response.error.message) || 'unknown error'));
      }
      return undefined;
    }
    const idToken = response.params && response.params.id_token;
    if (!idToken) {
      onError(
        'Google did not return an ID token — add this app\'s redirect URI to the OAuth client ' +
        '(sleepmonitor:// for the app, https://auth.expo.io for web).'
      );
      return undefined;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const result = await googleSignIn(idToken);
        if (cancelled) return;
        if (result.unavailable) setUnavailable(true);
        else if (result.needsRole) {
          pendingTokenRef.current = idToken;
          setNeedsRole(true);
        } else {
          onSession(result.user);
        }
      } catch (err) {
        if (!cancelled) onError(err.message || 'Google sign-in failed');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [response]);

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
        'Google sign-in needs a development build or the web app — Expo Go cannot ' +
        'complete the OAuth redirect (the auth proxy was removed from the SDK).'
      );
      return;
    }
    if (!GOOGLE_CONFIGURED) return;
    try {
      await promptAsync();
    } catch (err) {
      onError('Google sign-in could not open: ' + (err.message || 'unknown error'));
    }
  }

  return { prompt, needsRole, unavailable, loading, googleConfigured: GOOGLE_CONFIGURED, runningInExpoGo: RUNNING_IN_EXPO_GO, chooseRole, cancelRole };
}
