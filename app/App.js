import { useState, useEffect } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
} from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import { SleepProvider } from './context/SleepContext';
import { getStoredUser, logout, startSessionWatch } from './auth/apiAuth';
import LoginScreen     from './screens/LoginScreen';
import DoctorNavigator from './navigation/DoctorNavigator';

import HomeScreen    from './screens/HomeScreen';
import AlertsScreen  from './screens/AlertsScreen';
import ReportScreen  from './screens/ReportScreen';
import NetworkScreen from './screens/NetworkScreen';

const Tab = createBottomTabNavigator();

// ─── Patient: existing 4-tab navigator ───────────────────────────────────────

function PatientNavigator({ onLogout }) {
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
            paddingBottom:   10,
            height:          70,
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
      </Tab.Navigator>
    </NavigationContainer>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────

export default function App() {
  const [user, setUser]       = useState(null);
  const [loading, setLoading] = useState(true);

  // Check for persisted session on launch
  useEffect(() => {
    (async () => {
      const stored = await getStoredUser();
      setUser(stored);
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

  // ── Startup splash ──
  if (loading) {
    return (
      <View style={styles.splash}>
        <MaterialCommunityIcons name="sleep" size={48} color="#818cf8" />
        <ActivityIndicator color="#818cf8" style={{ marginTop: 24 }} />
      </View>
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
