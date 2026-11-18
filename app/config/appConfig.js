// Runtime config resolution. `extra` values are baked into the native app
// config at bundle/build time by app.config.js; EXPO_PUBLIC_* env vars are
// Metro-inlined at bundle time; defaults keep Expo Go dev working with no env
// set. See app/.env.example for the variable names.

import Constants from 'expo-constants';
import {
  DEFAULT_API_URL,
  DEFAULT_GOOGLE_CLIENT_ID,
  DEFAULT_MQTT_URL,
  parseMqttUrl,
  toMqttUrl,
} from './configDefaults';

const extra = (Constants.expoConfig && Constants.expoConfig.extra) || {};

export const API_URL = extra.apiUrl || process.env.EXPO_PUBLIC_API_URL || DEFAULT_API_URL;

export const MQTT_URL =
  toMqttUrl(extra.mqttUrl) ||
  toMqttUrl(process.env.EXPO_PUBLIC_MQTT_URL) ||
  toMqttUrl(process.env.EXPO_PUBLIC_BROKER_IP) || // legacy variable, still honoured
  DEFAULT_MQTT_URL;

export function getMqttEndpoint() {
  return parseMqttUrl(MQTT_URL);
}

// Unset = the auth API has no server-side Google client either; the login
// screen degrades to email/password only (the /auth/google 503 path).
export const GOOGLE_CLIENT_ID =
  extra.googleClientId || process.env.EXPO_PUBLIC_GOOGLE_CLIENT_ID || DEFAULT_GOOGLE_CLIENT_ID;

export const GOOGLE_CONFIGURED = Boolean(GOOGLE_CLIENT_ID);
