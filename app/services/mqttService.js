import Paho from 'paho-mqtt';
import AsyncStorage from '@react-native-async-storage/async-storage';

let client = null;
let onMessageHandler = null;
let onStatusChange = null;
let reconnectTimer = null;
let reconnectDelay = 1000;
let connecting = false;
// Bumped on connect/disconnect so a client ID resolve that lands after
// teardown (or a late broker callback) can't resurrect a connection.
let generation = 0;

// ── Broker host ───────────────────────────────────────
// Set EXPO_PUBLIC_BROKER_IP in app/.env.development (gitignored) — see
// app/.env.example. It is inlined at bundle time, so restart `npx expo start`
// after changing it. Find your laptop's LAN IP with `hostname -I` (Linux) or
// `ipconfig` (Windows); the phone must be on the same network.
const BROKER_IP = process.env.EXPO_PUBLIC_BROKER_IP || '192.168.68.68';
const BROKER_PORT = 9001;          // WebSocket port — important, use 9001 not 1883

// Broker credentials — the AWS broker runs locked (allow_anonymous false,
// see mosquitto/mosquitto.conf). On laptop dev the native broker is
// anonymous: Mosquitto ignores client-supplied credentials there, and Paho
// treats `undefined` as "connect with none", so the fallback is safe.
const BROKER_USER = process.env.EXPO_PUBLIC_MQTT_USER || undefined;
const BROKER_PASS = process.env.EXPO_PUBLIC_MQTT_PASSWORD || undefined;

const CLIENT_ID_KEY = 'mqtt_client_id';
const MAX_RECONNECT_DELAY = 10000;

/**
 * Per-install client ID, persisted locally. A stable ID is required for the
 * broker to keep a persistent session (cleanSession: false) and queue QoS 1/2
 * messages while the app is offline. A random per-install ID keeps two
 * different installs from kicking each other off the broker.
 * @returns {Promise<string>} the install's deterministic client ID
 */
async function getClientId() {
  try {
    let id = await AsyncStorage.getItem(CLIENT_ID_KEY);
    if (!id) {
      id = 'sm-' + Math.random().toString(36).slice(2, 10);
      await AsyncStorage.setItem(CLIENT_ID_KEY, id);
    }
    return id;
  } catch {
    return 'sm-' + Math.random().toString(36).slice(2, 10);
  }
}

/**
 * Schedules a reconnect attempt with exponential backoff (1s → MAX). A tie
 * applies a single pending timer at a time; `gen` guards against a torn-down
 * generation rescheduling itself.
 * @param {number} gen — the generation doing the reconnecting
 */
function scheduleReconnect(gen) {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    doConnect(gen);
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
}

/**
 * Connect (or reconnect after loss). The persistent session is what lets
 * the broker queue QoS 1/2 while the app is offline; `gen` guards against
 * a torn-down generation racing a late broker callback.
 * @param {number} gen — the generation attempting to connect
 */
function doConnect(gen) {
  if (gen !== generation || !client || connecting) return;
  connecting = true;
  const c = client;

  // Credential fields are attached only when real strings exist — anonymous
  // brokers (laptop dev) then connect with no credential fields at all,
  // instead of fields carrying `undefined`.
  const options = {
    // Explicit (do not rely on the Paho default): the persistent session is
    // what lets the broker queue QoS 1/2 while the app is disconnected.
    cleanSession: false,
    keepAliveInterval: 30,
    useSSL: false,
    onSuccess: () => {
      connecting = false;
      if (gen !== generation) return;
      reconnectDelay = 1000;
      console.log('MQTT connected via WebSocket');
      if (onStatusChange) onStatusChange(true);
      // Subscribe at QoS 2 so the broker does not downgrade critical/important
      // traffic; effective QoS is min(publishQoS, 2).
      c.subscribe('sleep/#', { qos: 2 });
      c.subscribe('qos/pong', { qos: 2 });
    },
    onFailure: (error) => {
      connecting = false;
      console.log('MQTT connection failed:', error.errorMessage);
      if (gen !== generation) return;
      if (onStatusChange) onStatusChange(false);
      scheduleReconnect(gen);
    },
  };
  if (BROKER_USER && BROKER_PASS) {
    options.userName = BROKER_USER;
    options.password = BROKER_PASS;
  }
  c.connect(options);
}

/**
 * Creates the Paho client for this generation, wires the connection-lost
 * and message-arrival callbacks, then connects.
 * @param {string} clientId — per-install ID (drives cleanSession:false queueing)
 * @param {number} gen — generation identity for this connect cycle
 */
function startClient(clientId, gen) {
  if (gen !== generation || client) return;
  const c = new Paho.Client(BROKER_IP, BROKER_PORT, clientId);
  client = c;

  c.onConnectionLost = (response) => {
    console.log('MQTT connection lost:', response.errorMessage);
    if (gen !== generation) return;
    if (onStatusChange) onStatusChange(false);
    scheduleReconnect(gen);
  };

  c.onMessageArrived = (message) => {
    try {
      const data = JSON.parse(message.payloadString);
      if (onMessageHandler) onMessageHandler(message.destinationName, data);
    } catch (e) {
      console.log('Parse error:', e);
    }
  };

  doConnect(gen);
}

/**
 * Entry point — SleepContext calls this with its message/status handlers.
 * Connects (or restarts) the MQTT client under a fresh generation; the
 * previous generation's timer/teardown can't resurrect a dead connection.
 * @param {function} onMessage — (topic, payloadObject) on every arrival
 * @param {function} [onStatus] — boolean status whenever connectivity changes
 */
export function connectMQTT(onMessage, onStatus = () => {}) {
  const gen = ++generation;
  onMessageHandler = onMessage;
  onStatusChange = onStatus;
  getClientId().then(id => startClient(id, gen));
}

/**
 * Publish a message at `qos`. Returns false when not connected — callers
 * should not treat that as fatal (Paho has no buffering here).
 */
export function publish(topic, payloadString, qos = 0) {
  if (client && client.isConnected()) {
    client.publish(topic, payloadString, qos, false);
    return true;
  }
  return false;
}

/** Connectivity probe — true only while a live Paho client is connected. */
export function isConnected() {
  return !!(client && client.isConnected());
}

/**
 * Full teardown: bumps the generation (orphaning timers and late broker
 * callbacks), clears reconnect state, and disconnects the live client.
 * Handlers clear after, so in-flight callbacks see no stale targets.
 */
export function disconnectMQTT() {
  generation += 1;
  connecting = false;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (client) {
    if (client.isConnected()) {
      client.disconnect();
      console.log('MQTT disconnected');
    }
    client = null;
  }
  onMessageHandler = null;
  onStatusChange = null;
}
