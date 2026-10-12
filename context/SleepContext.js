import { createContext, useContext, useState, useEffect } from 'react';
import { connectMQTT, disconnectMQTT } from '../services/mqttService';

const SleepContext = createContext(null);

export function SleepProvider({ children }) {

  const [currentData, setCurrentData] = useState({
    tier:        'Normal',
    spo2:        97,
    heartRate:   56,
    hrv:         35,
    motion:      0,
    timestamp:   '--:-- --',
    lastUpdated: 'Waiting...',
    reason:      '',
  });

  const [sessionStats, setSessionStats] = useState({
    critical:   0,
    important:  0,
    normal:     0,
    background: 0,
    total:      0,
  });

  const [spo2History, setSpo2History] = useState(
    Array(10).fill(97)
  );

  const [eventLog, setEventLog] = useState([]);

  const [sleepTimeline, setSleepTimeline] = useState([]);

  const [networkStats, setNetworkStats] = useState({
    connected:   false,
    critical:    { count: 0, latency: 0 },
    important:   { count: 0, latency: 0 },
    normal:      { count: 0, latency: 0 },
    background:  { count: 0, latency: 0 },
  });

  useEffect(() => {
    connectMQTT((topic, data) => {

      const now = Date.now();

      // Update current live reading
      setCurrentData({
        tier:        data.tier,
        spo2:        data.spo2,
        heartRate:   data.heartRate,
        hrv:         data.hrv,
        motion:      data.motion || 0,
        timestamp:   data.timestamp,
        lastUpdated: 'Just now',
        reason:      data.reason || '',
      });

      // Update session stats from payload
      if (data.stats) {
        setSessionStats({
          critical:   data.stats.critical,
          important:  data.stats.important,
          normal:     data.stats.normal,
          background: data.stats.background,
          total:      data.stats.total,
        });
      }

      // Update SpO2 history for sparkline
      setSpo2History(prev => {
        const updated = [...prev, data.spo2];
        return updated.slice(-10);
      });

      // Append to sleep timeline (capped at 120 entries)
      setSleepTimeline(prev => {
        const entry = {
          ts:        now,
          time:      data.timestamp,
          spo2:      data.spo2,
          heartRate: data.heartRate,
          hrv:       data.hrv,
          motion:    data.motion || 0,
          tier:      data.tier,
        };
        return [...prev, entry].slice(-120);
      });

      // Add to event log — only Critical and Important
      if (data.tier === 'Critical' || data.tier === 'Important') {
        setEventLog(prev => {
          const newEvent = {
            id:        String(now),
            tier:      data.tier,
            time:      data.timestamp,
            spo2:      data.spo2,
            hr:        data.heartRate,
            duration:  '—',
            topic:     data.topic,
            reason:    data.reason || '',
          };
          return [newEvent, ...prev].slice(0, 50);
        });
      }

      // Update network stats
      setNetworkStats(prev => {
        const tierKey = data.tier.toLowerCase();
        const prevTier = prev[tierKey] || { count: 0, latency: 0 };
        return {
          ...prev,
          connected: true,
          [tierKey]: {
            count:   prevTier.count + 1,
            latency: data.qos === 2 ? 12 :
                     data.qos === 1 ? 28 : 45,
          },
        };
      });

    });

    return () => disconnectMQTT();
  }, []);

  return (
    <SleepContext.Provider value={{
      currentData,
      sessionStats,
      spo2History,
      eventLog,
      networkStats,
      sleepTimeline,
    }}>
      {children}
    </SleepContext.Provider>
  );
}

export function useSleep() {
  return useContext(SleepContext);
}