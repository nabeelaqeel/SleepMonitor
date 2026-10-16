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

const CLIENT_ID_KEY = 'mqtt_client_id';
const MAX_RECONNECT_DELAY = 10000;

// Per-install client ID, persisted locally. A stable ID is required for the
// broker to keep a persistent session (cleanSession: false) and queue QoS 1/2
// messages while the app is offline. A random per-install ID keeps two
// different installs from kicking each other off the broker.
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

  c.connect({
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
  });
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

export function connectMQTT(onMessage, onStatus = () => {}) {
  const gen = ++generation;
  onMessageHandler = onMessage;
  onStatusChange = onStatus;
  getClientId().then(id => startClient(id, gen));
}

// Publish a message. Returns false when not connected (caller can ignore).
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
