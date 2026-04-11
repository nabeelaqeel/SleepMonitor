import Paho from 'paho-mqtt';

let client = null;

// ── Replace with your laptop IP address ───────────────
// Windows: open cmd → ipconfig → find IPv4 Address
// Mac:     open terminal → ifconfig | grep "inet "
const BROKER_IP = '192.168.1.139';  // CHANGE THIS to your laptop IP
const BROKER_PORT = 9001;          // WebSocket port — important, use 9001 not 1883

export function connectMQTT(onMessage) {
  const clientId = 'sleepmonitor_' + Math.random().toString(16).substr(2, 8);

  client = new Paho.Client(BROKER_IP, BROKER_PORT, clientId);

  client.onConnectionLost = (response) => {
    console.log('MQTT connection lost:', response.errorMessage);
  };

  client.onMessageArrived = (message) => {
    try {
      const data = JSON.parse(message.payloadString);
      onMessage(message.destinationName, data);
    } catch (e) {
      console.log('Parse error:', e);
    }
  };

  client.connect({
    onSuccess: () => {
      console.log('MQTT connected via WebSocket');
      client.subscribe('sleep/critical');
      client.subscribe('sleep/important');
      client.subscribe('sleep/normal');
      client.subscribe('sleep/background');
    },
    onFailure: (error) => {
      console.log('MQTT connection failed:', error.errorMessage);
    },
    useSSL: false,
  });
}

export function disconnectMQTT() {
  if (client && client.isConnected()) {
    client.disconnect();
    console.log('MQTT disconnected');
  }
}