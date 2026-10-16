// Seeded roster for the doctor dashboard. Real patient records live on the
// ingest side (Postgres); these entries keep the roster useful when no
// session is streaming.
//
// The entry that carries a `patientId` is the one that can go LIVE: it
// matches the publisher's PATIENT_ID, so SleepContext tracks its snapshots
// and the roster/detail/alerts screens overlay live values on top of it.
export const MOCK_PATIENTS = [
  {
    id: '2',
    name: 'Ali Hassan',
    patientId: 'patient-001',   // matches the publisher's PATIENT_ID — this row goes live
    age: 34,
    lastSpo2: 96,
    lastHr: 58,
    criticalEvents: 2,
    status: 'active',
    weight: 78,
    height: 175,
    medicalHistory: [
      { id: 'mh1', date: '2025-03-10', type: 'Diagnosis',   note: 'Mild obstructive sleep apnea (AHI 8.2/hr)',              doctor: 'Dr. Ahmad' },
      { id: 'mh2', date: '2025-01-22', type: 'Medication',  note: 'Prescribed CPAP therapy (8 cmH2O)',                      doctor: 'Dr. Ahmad' },
      { id: 'mh3', date: '2024-11-05', type: 'Lab Result',  note: 'Overnight polysomnography — AHI 8.2, SpO2 nadir 91%',   doctor: 'Dr. Lim'   },
    ],
  },
  {
    id: '3',
    name: 'Siti Aminah',
    age: 28,
    lastSpo2: 94,
    lastHr: 62,
    criticalEvents: 0,
    status: 'sleeping',
    weight: 55,
    height: 160,
    medicalHistory: [
      { id: 'mh1', date: '2025-04-18', type: 'Diagnosis',  note: 'Upper airway resistance syndrome, mild',      doctor: 'Dr. Farah' },
      { id: 'mh2', date: '2025-02-09', type: 'Lab Result', note: 'CBC and thyroid panel — within normal limits', doctor: 'Dr. Farah' },
    ],
  },
  {
    id: '4',
    name: 'Rahman Ismail',
    age: 51,
    lastSpo2: 88,
    lastHr: 71,
    criticalEvents: 5,
    status: 'critical',
    weight: 95,
    height: 168,
    medicalHistory: [
      { id: 'mh1', date: '2025-05-01', type: 'Diagnosis',  note: 'Severe obstructive sleep apnea (AHI 34/hr)',        doctor: 'Dr. Ahmad' },
      { id: 'mh2', date: '2025-04-15', type: 'Medication', note: 'BiPAP — IPAP 14 cmH2O / EPAP 8 cmH2O',             doctor: 'Dr. Ahmad' },
      { id: 'mh3', date: '2025-03-30', type: 'Medication', note: 'Supplemental oxygen (2 L/min nasal cannula)',       doctor: 'Dr. Ahmad' },
      { id: 'mh4', date: '2025-01-12', type: 'Lab Result', note: 'ABG: pH 7.36, PaO2 68 mmHg, PaCO2 48 mmHg',       doctor: 'Dr. Lim'   },
    ],
  },
];
