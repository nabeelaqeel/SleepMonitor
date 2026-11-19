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
import AcknowledgementScreen   from './screens/AcknowledgementScreen';
import ProfileScreen           from './screens/ProfileScreen';
import DoctorNavigator from './navigation/DoctorNavigator';

import HomeScreen    from './screens/HomeScreen';
import DeviceScreen  from './screens/DeviceScreen';
import AlertsScreen  from './screens/AlertsScreen';
import ReportScreen  from './screens/ReportScreen';
import NetworkScreen from './screens/NetworkScreen';
import { ACK_STORAGE_KEY, PROFILE } from './config/displayText';

const Tab = createBottomTabNavigator();

function PatientNavigator({ onLogout, user, onUserUpdated }) {
  // Edge-to-edge: our tabBarStyle overrides bottom-tabs' safe-area padding, so
  // feed the Android system-nav-bar inset back in (large with 3-button nav only).
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
        <Tab.Screen name="Device" component={DeviceScreen}
          options={{ title: 'My Device', tabBarIcon: ({ color, size }) => <MaterialCommunityIcons name="watch-variant" color={color} size={size} /> }}
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
        <Tab.Screen name="Profile"
          options={{
            title: PROFILE.tabTitle,
            tabBarIcon: ({ color, size }) => (
              <MaterialCommunityIcons name="account-circle" color={color} size={size} />
            ),
          }}
        >
          {() => <ProfileScreen user={user} onLogout={onLogout} onUserUpdated={onUserUpdated} />}
        </Tab.Screen>
      </Tab.Navigator>
    </NavigationContainer>
  );
}

export default function App() {
  const [user, setUser]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [acked, setAcked]     = useState(false);

  useEffect(() => {
    (async () => {
      const stored = await getStoredUser();
      setUser(stored);
      const ackValue = await AsyncStorage.getItem(ACK_STORAGE_KEY);
      setAcked(ackValue === '1');
      setLoading(false);
    })();
  }, []);

  // Re-validate the exp every minute for EVERY authenticated session (including
  // ones created after mount); the cleanup stops the watcher so no stale callback fires.
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

  if (loading) {
    return (
      <View style={styles.splash}>
        <MaterialCommunityIcons name="sleep" size={48} color="#818cf8" />
        <ActivityIndicator color="#818cf8" style={{ marginTop: 24 }} />
      </View>
    );
  }

  // First launch: the disclaimer must be agreed before anyone reaches data screens (both roles).
  if (!acked) {
    return (
      <SafeAreaProvider>
        <AcknowledgementScreen onAgree={handleAgree} />
      </SafeAreaProvider>
    );
  }

  if (!user) {
    // No provider pre-login: it would run in doctor mode (patientId null),
    // ingest the whole stream, and the instance survives into the patient
    // session — carrying another patient's data across the login boundary.
    return (
      <SafeAreaProvider>
        <LoginScreen onLoginSuccess={handleLoginSuccess} />
      </SafeAreaProvider>
    );
  }

  if (user.role === 'doctor') {
    return (
      <SafeAreaProvider>
        <SleepProvider>
          <DoctorNavigator onLogout={handleLogout} user={user} onUserUpdated={setUser} />
        </SleepProvider>
      </SafeAreaProvider>
    );
  }

  return (
    <SafeAreaProvider>
      <SleepProvider patientId={user.patientId || user.id}>
        <PatientNavigator onLogout={handleLogout} user={user} onUserUpdated={setUser} />
      </SleepProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    backgroundColor: '#0a0a0f',
    alignItems: 'center',
    justifyContent: 'center',
  },

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
