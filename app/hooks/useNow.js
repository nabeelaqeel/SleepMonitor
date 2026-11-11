import { useEffect, useState } from 'react';

// Re-renders on an interval so time-based UI (LIVE badges, "last seen") can go stale without new MQTT messages.
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return now;
}
