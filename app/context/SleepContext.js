import { createContext, useContext, useState, useEffect, useRef } from 'react';
import { connectMQTT, disconnectMQTT, publish } from '../services/mqttService';

const SleepContext = createContext(null);

// Monotonic clock for RTT measurement — immune to wall-clock/NTP steps.
const nowMs = () =>
  (typeof performance !== 'undefined' && performance.now)
    ? performance.now()
    : Date.now();

// Latency probe tuning.
const PING_INTERVAL_MS  = 1000;   // one ping per tick, cycling QoS 2 → 1 → 0
const PING_TIMEOUT_MS   = 5000;   // drop a ping that never returns (memory guard)
const SAMPLE_TTL_MS     = 15000;  // forget completed samples older than this → "—"
const MAX_SAMPLES       = 21;     // hard cap per QoS window
const QoS_CYCLE         = [2, 1, 0];

// Doctor roster: a patient counts as "live" while messages bearing its
// patientId keep arriving; after this gap the roster shows "last seen".
export const PATIENT_LIVE_WINDOW_MS = 10000;

const INSTANCE_ID = Math.random().toString(36).slice(2, 8);

// Event-log ids are derived from the ingest timestamp, but a timestamp alone
// can collide when messages arrive in a burst (queued QoS 1/2 redelivery
// after a reconnect, fast replay, batched delivery) — duplicate React keys.
let eventIdCounter = 0;

function median(sorted) {
  const n = sorted.length;
  if (n === 0) return null;
  const mid = Math.floor(n / 2);
  const m = n % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  return Math.round(m * 100) / 100;
}

const AWAITING_AI_RECOMMENDATION = {
  band: null,
  disclaimer: 'Awaiting nightly analysis.',
};

export function SleepProvider({ children, patientId = null }) {

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
    critical:    { count: 0, delivery: null },
    important:   { count: 0, delivery: null },
    normal:      { count: 0, delivery: null },
    background:  { count: 0, delivery: null },
  });

  // Estimated latency (RTT/2) per QoS level, as { ms, samples }.
  const [latencyStats, setLatencyStats] = useState({
    0: { ms: null, samples: 0 },
    1: { ms: null, samples: 0 },
    2: { ms: null, samples: 0 },
  });

  // Last reading per payload patientId — powers the doctor roster's LIVE
  // badge. Only the patient that is actually streaming updates here.
  const [patientSnapshots, setPatientSnapshots] = useState({});

  // Optional AI recommendation (post-night guidance band, non QoS tier)
  const [aiRecommendations, setAiRecommendations] = useState({});

  // ── Mutable measurement state (no re-render churn) ───────────
  const pendingRef  = useRef({});                       // pingId → { t0, qos, at }
  const samplesRef  = useRef({ 0: [], 1: [], 2: [] });  // qos → [{ t, value }]
  const deliveryRef = useRef({
    sessionId: null,
    base:  {},   // tierKey → stats[tier] at (or just before) first sight
    seqs:  {},   // tierKey → Set of seq (dedup)
    count: {},   // tierKey → distinct received since base
  });

  const recomputeLatency = () => {
    const next = {};
    for (const q of [0, 1, 2]) {
      const vals = samplesRef.current[q].map(s => s.value).sort((a, b) => a - b);
      next[q] = { ms: median(vals), samples: vals.length };
    }
    setLatencyStats(next);
  };

  // Records delivery using the delta since the app joined this session, so a
  // late-joining app still starts near 100% (pre-join publishes are excluded
  // from both numerator and denominator). Resets on sessionId change.
  const recordDelivery = (data) => {
    const key = (data.tier || 'Normal').toLowerCase();
    const acc = deliveryRef.current;
    const sid = data.sessionId;

    // Reset the window only when we can actually identify a new session.
    if (sid !== undefined && sid !== null && acc.sessionId !== sid) {
      acc.sessionId = sid;
      acc.base  = {};
      acc.seqs  = {};
      acc.count = {};
      if (patientId) {
        setAiRecommendations(prev => ({
          ...prev,
          [patientId]: AWAITING_AI_RECOMMENDATION,
        }));
      }
    }
    if (acc.base[key] === undefined) {
      const published = data.stats && data.stats[key];
      // Establish the baseline only once a payload carries the counter;
      // otherwise a wrong denominator would understate delivery.
      if (typeof published !== 'number') {
        return { key, count: acc.count[key] || 0, delivery: null };
      }
      acc.base[key]  = published - 1;
      acc.seqs[key]  = new Set();
      acc.count[key] = 0;
    }

    const seen = acc.seqs[key];
    const seqKey = (data.seq !== undefined) ? data.seq : `${key}-${Date.now()}`;
    if (!seen.has(seqKey)) {
      seen.add(seqKey);
      acc.count[key] += 1;
    }

    const published = data.stats && data.stats[key];
    let delivery = null;
    if (typeof published === 'number') {
      const denom = published - acc.base[key];
      delivery = denom > 0
        ? Math.min(100, Math.round((acc.count[key] / denom) * 100))
        : null;
    }
    return { key, count: acc.count[key], delivery };
  };

  const handleMessage = (topic, data) => {
    // ── Latency probe response ────────────────────────────────
    if (topic === 'qos/pong') {
      const p = pendingRef.current[data.pingId];
      if (p) {
        const rtt = nowMs() - p.t0;
        samplesRef.current[p.qos].push({ t: nowMs(), value: rtt / 2 });
        if (samplesRef.current[p.qos].length > MAX_SAMPLES) {
          samplesRef.current[p.qos].shift();
        }
        delete pendingRef.current[data.pingId];
        recomputeLatency();
      }
      return;
    }

    // Optional AI recommendation (post-night guidance band, non QoS tier)
    if (topic === 'sleep/recommendation') {
      if (data.patientId) {
        setAiRecommendations(prev => ({
          ...prev,
          [data.patientId]: data,
        }));
      }
      return;
    }

    if (!topic.startsWith('sleep/')) return;

    const now = Date.now();
    // sleep/background carries two message kinds: periodic statistics carry
    // no seq, while genuine Background-tier readings do (out-of-band values
    // classified by tier_rules). Only the stats kind is "stats-only" here —
    // readings must flow through the live display like any other tier.
    const isStatsOnly = topic === 'sleep/background' && data.seq === undefined;

    if (!isStatsOnly) {
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
            id:        `${now}-${++eventIdCounter}`,
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
    }

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

    // Update network stats (real delivery measured against publisher stats)
    const { key, count, delivery } = recordDelivery(data);
    setNetworkStats(prev => ({
      ...prev,
      connected: true,
      [key]: { count, delivery },
    }));

    // Per-patient snapshot for the doctor roster. Stats-only background
    // messages carry no vitals, so they only refresh lastSeen; Background
    // readings (with seq) update the vitals overlay like other tiers.
    if (data.patientId) {
      setPatientSnapshots(prev => {
        const prior = prev[data.patientId] || {};
        return {
          ...prev,
          [data.patientId]: isStatsOnly
            ? { ...prior, lastSeen: now }
            : {
                ...prior,
                lastSeen:  now,
                tier:      data.tier,
                spo2:      data.spo2,
                heartRate: data.heartRate,
                hrv:       data.hrv,
                topic:     data.topic,
                timestamp: data.timestamp,
              },
        };
      });
    }
  };

  useEffect(() => {
    connectMQTT(handleMessage, (isConn) => {
      setNetworkStats(prev => ({ ...prev, connected: isConn }));
    });

    let pingSeq = 0;
    let cycleIdx = 0;

    const tick = () => {
      const now = nowMs();

      // Drop unanswered pings (memory guard when echo.py is down)
      for (const id of Object.keys(pendingRef.current)) {
        if (now - pendingRef.current[id].at > PING_TIMEOUT_MS) {
          delete pendingRef.current[id];
        }
      }

      // Expire stale completed samples so the median trails recent conditions
      // and the readout flips to "—" once the echo responder stops.
      for (const q of [0, 1, 2]) {
        samplesRef.current[q] = samplesRef.current[q]
          .filter(s => now - s.t <= SAMPLE_TTL_MS);
      }
      recomputeLatency();

      // Send this tick's ping
      const qos = QoS_CYCLE[cycleIdx % QoS_CYCLE.length];
      cycleIdx += 1;
      const pingId = `${INSTANCE_ID}-${pingSeq++}`;
      pendingRef.current[pingId] = { t0: now, qos, at: now };
      publish('qos/ping', JSON.stringify({ type: 'ping', pingId, qos }), qos);
    };

    const interval = setInterval(tick, PING_INTERVAL_MS);

    return () => {
      clearInterval(interval);
      disconnectMQTT();
    };
  }, []);

  return (
    <SleepContext.Provider value={{
      currentData,
      sessionStats,
      spo2History,
      eventLog,
      networkStats,
      latencyStats,
      sleepTimeline,
      patientSnapshots,
      // Raw per-patient recommendation map — doctor screens pick their
      // patient's entry here (aiRecommendation below is only for the patient
      // app, where the provider was mounted with a patientId).
      aiRecommendations,
      aiRecommendation: patientId
        ? aiRecommendations[patientId] || AWAITING_AI_RECOMMENDATION
        : AWAITING_AI_RECOMMENDATION,
    }}>
      {children}
    </SleepContext.Provider>
  );
}

export function useSleep() {
  return useContext(SleepContext);
}
