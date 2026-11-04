import { useEffect, useState } from 'react';

// Re-renders the calling component on an interval so time-based UI (LIVE
// badges, "last seen" labels) can go stale without new MQTT messages arriving.
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return now;
}
