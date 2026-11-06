import { useState, useEffect } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import { SleepProvider } from './context/SleepContext';
import { getStoredUser, logout, startSessionWatch } from './auth/apiAuth';
import LoginScreen             from './screens/LoginScreen';
import AboutScreen             from './screens/AboutScreen';
import AcknowledgementScreen   from './screens/AcknowledgementScreen';
import DoctorNavigator from './navigation/DoctorNavigator';

import HomeScreen    from './screens/HomeScreen';
import AlertsScreen  from './screens/AlertsScreen';
import ReportScreen  from './screens/ReportScreen';
import NetworkScreen from './screens/NetworkScreen';
import { ACK_STORAGE_KEY } from './config/displayText';

const Tab = createBottomTabNavigator();

// ─── Patient: existing 4-tab navigator ───────────────────────────────────────

function PatientNavigator({ onLogout }) {
  // The app draws edge-to-edge, so lift the tab bar contents above the
  // Android system nav bar when the phone uses 3-button navigation
  // (insets.bottom ~48dp); gesture navigation has a tiny inset, keeping
  // the bar near-compact there. Our tabBarStyle overrides bottom-tabs'
  // own safe-area padding, so we have to feed the inset back in.
  const { bottom } = useSafeAreaInsets();

  return (
    <NavigationContainer>
      <Tab.Navigator
        screenOptions={{
          headerShown: true,
          headerStyle:            { backgroundColor: '#0a0a0f' },
          headerTintColor:        '#e2e8f0',
          headerTitleStyle:       { fontWeight: '600' },
          headerRight: () => (
            <TouchableOpacity onPress={onLogout} style={styles.logoutBtn}>
              <MaterialCommunityIcons name="logout" size={20} color="#818cf8" />
              <Text style={styles.logoutText}>Logout</Text>
            </TouchableOpacity>
          ),
          tabBarStyle: {
            backgroundColor: '#0a0a0f',
            borderTopColor:  '#1a1a2e',
            borderTopWidth:  0.5,
            paddingBottom:   bottom,
            height:          60 + bottom,
          },
          tabBarActiveTintColor:   '#818cf8',
          tabBarInactiveTintColor: '#444',
        }}
      >
        <Tab.Screen name="Home" component={HomeScreen}
          options={{ tabBarIcon: ({ color, size }) => <MaterialCommunityIcons name="home" color={color} size={size} /> }}
        />
        <Tab.Screen name="Alerts" component={AlertsScreen}
          options={{ tabBarIcon: ({ color, size }) => <MaterialCommunityIcons name="bell-alert" color={color} size={size} /> }}
        />
        <Tab.Screen name="Report" component={ReportScreen}
          options={{ tabBarIcon: ({ color, size }) => <MaterialCommunityIcons name="chart-bar" color={color} size={size} /> }}
        />
        <Tab.Screen name="Network" component={NetworkScreen}
          options={{ tabBarIcon: ({ color, size }) => <MaterialCommunityIcons name="wifi" color={color} size={size} /> }}
        />
        <Tab.Screen name="About" component={AboutScreen}
          options={{
            title: 'About',
            tabBarIcon: ({ color, size }) => (
              <MaterialCommunityIcons name="information-outline" color={color} size={size} />
            ),
          }}
        />
      </Tab.Navigator>
    </NavigationContainer>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────

export default function App() {
  const [user, setUser]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [acked, setAcked]     = useState(false);

  // Check for persisted session — and the first-launch disclaimer
  // acknowledgement — on launch
  useEffect(() => {
    (async () => {
      const stored = await getStoredUser();
      setUser(stored);
      const ackValue = await AsyncStorage.getItem(ACK_STORAGE_KEY);
      setAcked(ackValue === '1');
      setLoading(false);
    })();
  }, []);

  // Re-validate the exp every minute for EVERY authenticated session —
  // including one created after this screen mounted — and stop the watcher
  // on logout/unmount (the effect's cleanup) so no stale callback can fire.
  useEffect(() => {
    if (!user) return undefined; // splash / logged-out — nothing to watch
    return startSessionWatch(() => setUser(null));
  }, [user && user.id]);

  function handleLoginSuccess(loggedInUser) {
    setUser(loggedInUser);
  }

  async function handleLogout() {
    await logout();
    setUser(null);
  }

  async function handleAgree() {
    await AsyncStorage.setItem(ACK_STORAGE_KEY, '1');
    setAcked(true);
  }

  // ── Startup splash ──
  if (loading) {
    return (
      <View style={styles.splash}>
        <MaterialCommunityIcons name="sleep" size={48} color="#818cf8" />
        <ActivityIndicator color="#818cf8" style={{ marginTop: 24 }} />
      </View>
    );
  }

  // ── First launch: research disclaimer acknowledgement, both roles ──
  // Checked before login so nobody reaches data screens before agreeing.
  if (!acked) {
    return (
      <SafeAreaProvider>
        <AcknowledgementScreen onAgree={handleAgree} />
      </SafeAreaProvider>
    );
  }

  // ── Not logged in ──
  if (!user) {
    return (
      <SafeAreaProvider>
        <SleepProvider>
          <LoginScreen onLoginSuccess={handleLoginSuccess} />
        </SleepProvider>
      </SafeAreaProvider>
    );
  }

  // ── Logged in: Doctor ──
  if (user.role === 'doctor') {
    return (
      <SafeAreaProvider>
        <SleepProvider>
          <DoctorNavigator onLogout={handleLogout} />
        </SleepProvider>
      </SafeAreaProvider>
    );
  }

  // ── Logged in: Patient ──
  return (
    <SafeAreaProvider>
      <SleepProvider patientId={user.patientId || user.id}>
        <PatientNavigator onLogout={handleLogout} />
      </SleepProvider>
    </SafeAreaProvider>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  // Startup splash
  splash: {
    flex: 1,
    backgroundColor: '#0a0a0f',
    alignItems: 'center',
    justifyContent: 'center',
  },

  // Patient navigator — logout button in header
  logoutBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginRight: 16,
  },
  logoutText: {
    color: '#818cf8',
    fontSize: 14,
    fontWeight: '500',
  },

});
