import Paho from 'paho-mqtt';
import AsyncStorage from '@react-native-async-storage/async-storage';

let client = null;
let onMessageHandler = null;
let onStatusChange = null;
let reconnectTimer = null;
let reconnectDelay = 1000;
let connecting = false;
// Bumped on connect/disconnect so a late resolve or broker callback can't resurrect a torn-down connection.
let generation = 0;

// EXPO_PUBLIC_BROKER_IP (app/.env.development, gitignored — see app/.env.example)
// is inlined at bundle time: restart `npx expo start` after changing it.
const BROKER_IP = process.env.EXPO_PUBLIC_BROKER_IP || '192.168.68.68';
const BROKER_PORT = 9001;          // WebSocket port — important, use 9001 not 1883

// AWS broker runs locked; laptop-dev broker is anonymous (Mosquitto ignores credentials), so the fallback is safe.
const BROKER_USER = process.env.EXPO_PUBLIC_MQTT_USER || undefined;
const BROKER_PASS = process.env.EXPO_PUBLIC_MQTT_PASSWORD || undefined;

const CLIENT_ID_KEY = 'mqtt_client_id';
const MAX_RECONNECT_DELAY = 10000;

/** Per-install persisted ID — stable so the broker's persistent session keeps
 *  queueing while offline; random per install so two installs can't kick each other off. */
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

// Exponential backoff (1s → MAX); `gen` guards a torn-down generation from rescheduling.
function scheduleReconnect(gen) {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    doConnect(gen);
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
}

function doConnect(gen) {
  if (gen !== generation || !client || connecting) return;
  connecting = true;
  const c = client;

  // Attach credential fields only when real strings exist — anonymous brokers then connect with none instead of `undefined`s.
  const options = {
    // Explicit: persistent session lets the broker queue QoS 1/2 while disconnected (see getClientId).
    cleanSession: false,
    keepAliveInterval: 30,
    useSSL: false,
    onSuccess: () => {
      connecting = false;
      if (gen !== generation) return;
      reconnectDelay = 1000;
      console.log('MQTT connected via WebSocket');
      if (onStatusChange) onStatusChange(true);
      // QoS 2 so the broker can't downgrade critical/important traffic (effective QoS = min(publishQoS, 2)).
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

/** Entry point — SleepContext calls this with its message/status handlers. */
export function connectMQTT(onMessage, onStatus = () => {}) {
  const gen = ++generation;
  onMessageHandler = onMessage;
  onStatusChange = onStatus;
  getClientId().then(id => startClient(id, gen));
}

/** Publish at `qos`; returns false when not connected — callers must not treat that as fatal (no buffering here). */
export function publish(topic, payloadString, qos = 0) {
  if (client && client.isConnected()) {
    client.publish(topic, payloadString, qos, false);
    return true;
  }
  return false;
}

export function isConnected() {
  return !!(client && client.isConnected());
}

/** Full teardown: bumps the generation (orphaning timers and late callbacks),
 *  clears reconnect state, disconnects, then clears handlers so in-flight
 *  callbacks see no stale targets. */
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
