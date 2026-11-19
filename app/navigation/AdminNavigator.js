import { TouchableOpacity, Text, StyleSheet } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import NetworkScreen    from '../screens/admin/NetworkScreen';
import AdminUsersScreen from '../screens/admin/AdminUsersScreen';
import ProfileScreen    from '../screens/ProfileScreen';

import { PROFILE } from '../config/displayText';

const Tab   = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

function SystemStack({ onLogout }) {
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
        name="SystemStatus"
        component={NetworkScreen}
        options={{
          title: 'System status',
          headerRight: () => (
            <TouchableOpacity onPress={onLogout} style={styles.logoutBtn}>
              <MaterialCommunityIcons name="logout" size={20} color="#818cf8" />
              <Text style={styles.logoutText}>Logout</Text>
            </TouchableOpacity>
          ),
        }}
      />
    </Stack.Navigator>
  );
}

// Same structure as DoctorNavigator: stack-wrapped first tab (header owns the
// logout), flat second tab, Profile opts back into the navigator header.
export default function AdminNavigator({ onLogout, user, onUserUpdated }) {
  const { bottom } = useSafeAreaInsets();

  return (
    <NavigationContainer>
      <Tab.Navigator
        screenOptions={{
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
          name="System"
          options={{
            tabBarIcon: ({ color, size }) => (
              <MaterialCommunityIcons name="monitor-dashboard" color={color} size={size} />
            ),
          }}
        >
          {() => <SystemStack onLogout={onLogout} />}
        </Tab.Screen>

        <Tab.Screen
          name="Users"
          component={AdminUsersScreen}
          options={{
            tabBarIcon: ({ color, size }) => (
              <MaterialCommunityIcons name="account-group" color={color} size={size} />
            ),
          }}
        />

        <Tab.Screen
          name="Profile"
          options={{
            headerShown: true,
            title: PROFILE.tabTitle,
            headerStyle:      { backgroundColor: '#0a0a0f' },
            headerTintColor:  '#e2e8f0',
            headerTitleStyle: { fontWeight: '600' },
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
