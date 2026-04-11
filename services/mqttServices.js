import MQTT from 'async-mqtt';

const BROKER_URL = 'mqtt://YOUR_LAPTOP_IP:1883';
// Replace YOUR_LAPTOP_IP with your laptop's local IP address
// On Windows: open cmd → type ipconfig → look for IPv4 Address
// Example: 'mqtt://192.168.1.5:1883'

let client = null;

export async function connectMQTT(onMessage) {
  try {
    client = await MQTT.connectAsync(BROKER_URL);
    console.log('MQTT connected');

    await client.subscribe('sleep/critical');
    await client.subscribe('sleep/important');
    await client.subscribe('sleep/normal');
    await client.subscribe('sleep/background');

    client.on('message', (topic, message) => {
      try {
        const data = JSON.parse(message.toString());
        onMessage(topic, data);
      } catch (e) {
        console.log('Parse error:', e);
      }
    });

  } catch (e) {
    console.log('MQTT connection error:', e);
  }
}

export async function disconnectMQTT() {
  if (client) {
    await client.end();
    console.log('MQTT disconnected');
  }
}