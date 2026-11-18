// Roster ↔ MQTT join, shared by the doctor's list and alerts screens: the API
// roster (GET /patients) is the data source, fresh device snapshots are the
// liveness signal.
import { useState, useCallback } from 'react';
import { useFocusEffect } from '@react-navigation/native';
import { PATIENT_LIVE_WINDOW_MS } from '../../context/SleepContext';
import { fetchPatients } from '../../auth/apiAuth';

/** GET /patients rows are snake_case; map once so cards and the detail route
 *  share one shape. Mock-shaped fields stay optional — real rows omit them. */
export function mapRosterPatient(row) {
  return {
    id: row.id,
    email: row.email,
    name: row.name,
    // Live snapshots are keyed by the publisher's patientId, which the roster
    // does not carry — liveness joins run through devices[] + deviceId below.
    patientId: row.patientId,
    lastSpo2: row.last_reading ? row.last_reading.spo2 : null,
    lastHr: row.last_reading ? row.last_reading.heart_rate : null,
    lastReadingTs: row.last_reading ? row.last_reading.ts : null,
    lastSession: row.last_session || null,
    devices: row.devices || [],
    // Roster carries no physical metrics — detail screen renders '—' for them.
    age: row.age,
    weight: row.weight,
    height: row.height,
    medicalHistory: row.medicalHistory,
  };
}

/** A row is LIVE when ANY bound device has a snapshot fresher than the live
 *  window; multiple devices → the freshest snapshot wins. lastSeen has ms
 *  resolution, so equal timestamps break by delivery order (later wins). */
export function pickLiveDevice(patient, deviceSnapshots, now) {
  let freshest = null;
  for (const device of patient.devices) {
    const snap = deviceSnapshots[device.device_id];
    if (!snap) continue;
    if (now - snap.lastSeen >= PATIENT_LIVE_WINDOW_MS) continue;
    if (!freshest || snap.lastSeen >= freshest.lastSeen) freshest = snap;
  }
  return freshest;
}

/** Tiny focus-scoped roster hook for screens that only need names/alerts.
 *  Fetch failures degrade to an empty roster — never blocks the alerts view. */
export function useRoster() {
  const [patients, setPatients] = useState([]);

  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      fetchPatients()
        .then(rows => { if (!cancelled) setPatients(rows.map(mapRosterPatient)); })
        .catch(() => { /* keep whatever roster we have; alerts still work */ });
      return () => { cancelled = true; };
    }, [])
  );

  return patients;
}
