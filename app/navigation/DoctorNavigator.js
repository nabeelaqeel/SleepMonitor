import { TouchableOpacity, Text, StyleSheet } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import PatientListScreen   from '../screens/doctor/PatientListScreen';
import PatientDetailScreen from '../screens/doctor/PatientDetailScreen';
import DoctorAlertsScreen  from '../screens/doctor/DoctorAlertsScreen';
import AboutScreen         from '../screens/AboutScreen';

const Tab   = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

function PatientsStack({ onLogout }) {
  return (
    <Stack.Navigator
      screenOptions={{
        headerStyle:      { backgroundColor: '#0a0a0f' },
        headerTintColor:  '#e2e8f0',
        headerTitleStyle: { fontWeight: '600' },
        contentStyle:     { backgroundColor: '#0a0a0f' },
      }}
    >
      <Stack.Screen
        name="PatientList"
        component={PatientListScreen}
        options={{
          title: 'Doctor Dashboard',
          headerRight: () => (
            <TouchableOpacity onPress={onLogout} style={styles.logoutBtn}>
              <MaterialCommunityIcons name="logout" size={20} color="#818cf8" />
              <Text style={styles.logoutText}>Logout</Text>
            </TouchableOpacity>
          ),
        }}
      />
      <Stack.Screen
        name="PatientDetail"
        component={PatientDetailScreen}
        options={({ route }) => ({ title: route.params.patient.name })}
      />
    </Stack.Navigator>
  );
}

export default function DoctorNavigator({ onLogout }) {
  // Same edge-to-edge inset handling as PatientNavigator in App.js.
  const { bottom } = useSafeAreaInsets();

  return (
    <NavigationContainer>
      <Tab.Navigator
        screenOptions={{
          // Both tabs render their own headers, so the navigator stays bare.
          headerShown: false,
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
        <Tab.Screen
          name="Patients"
          options={{
            tabBarIcon: ({ color, size }) => (
              <MaterialCommunityIcons name="account-multiple" color={color} size={size} />
            ),
          }}
        >
          {() => <PatientsStack onLogout={onLogout} />}
        </Tab.Screen>

        <Tab.Screen
          name="Alerts"
          component={DoctorAlertsScreen}
          options={{
            tabBarIcon: ({ color, size }) => (
              <MaterialCommunityIcons name="bell-alert" color={color} size={size} />
            ),
          }}
        />

        <Tab.Screen
          name="About"
          component={AboutScreen}
          options={{
            tabBarIcon: ({ color, size }) => (
              <MaterialCommunityIcons name="information-outline" color={color} size={size} />
            ),
          }}
        />
      </Tab.Navigator>
    </NavigationContainer>
  );
}

const styles = StyleSheet.create({
  logoutBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  logoutText: {
    color: '#818cf8',
    fontSize: 14,
    fontWeight: '500',
  },
});
