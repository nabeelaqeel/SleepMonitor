import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEY = 'current_user';

export const MOCK_USERS = [
  {
    id: '1',
    email: 'doctor@sleep.com',
    password: '1234',
    role: 'doctor',
    name: 'Dr. Ahmad',
  },
  {
    id: '2',
    email: 'patient@sleep.com',
    password: '1234',
    role: 'patient',
    name: 'Ali Hassan',
    patientId: '00000000-0000-0000-0000-000000000002',
  },
];

export function login(email, password) {
  const match = MOCK_USERS.find(
    u => u.email === email && u.password === password
  );
  if (!match) return null;
  const { password: _omit, ...user } = match;
  return user;
}

export async function logout() {
  await AsyncStorage.removeItem(STORAGE_KEY);
}

export async function getStoredUser() {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export async function storeUser(user) {
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(user));
}
