// Shared build-time config defaults. Required by app.config.js (Node/CommonJS)
// and by the runtime reader (config/appConfig.js via Metro) so both agree.

const DEFAULT_API_URL = 'http://192.168.0.29:8000';
const DEFAULT_MQTT_URL = 'ws://192.168.68.68:9001';
const DEFAULT_MQTT_PORT = 9001;
const DEFAULT_GOOGLE_CLIENT_ID = '';

/** Normalises a broker value into a ws:// URL. Accepts a full ws(s):// URL, an
 *  http(s):// URL (protocol swapped), or a bare host/IP (legacy
 *  EXPO_PUBLIC_BROKER_IP) which gets the default WebSocket port. */
function toMqttUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return '';
  const v = value.trim();
  if (/^wss?:\/\//i.test(v)) return v;
  if (/^https?:\/\//i.test(v)) return v.replace(/^http/i, 'ws');
  return `ws://${v}${v.includes(':') ? '' : ':' + DEFAULT_MQTT_PORT}`;
}

/** Splits a ws:// or wss:// broker URL into the Paho client fields. */
function parseMqttUrl(url) {
  const full = toMqttUrl(url) || DEFAULT_MQTT_URL;
  try {
    const u = new URL(full);
    const useSSL = u.protocol === 'wss:' || u.protocol === 'https:';
    if (!u.hostname) throw new Error('missing host');
    const port = Number(u.port) || (useSSL ? 443 : DEFAULT_MQTT_PORT);
    return { host: u.hostname, port, useSSL };
  } catch (err) {
    throw new Error(
      `Invalid MQTT broker URL '${url}' — expected ws://host:port (or wss://host:port).`
    );
  }
}

module.exports = {
  DEFAULT_API_URL,
  DEFAULT_MQTT_URL,
  DEFAULT_GOOGLE_CLIENT_ID,
  toMqttUrl,
  parseMqttUrl,
};
