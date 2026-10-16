import { TouchableOpacity, Text, StyleSheet } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import PatientListScreen   from '../screens/doctor/PatientListScreen';
import PatientDetailScreen from '../screens/doctor/PatientDetailScreen';

const Stack = createNativeStackNavigator();

export default function DoctorNavigator({ onLogout }) {
  return (
    <NavigationContainer>
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
          options={{
            title: 'Doctor Dashboard',
            headerRight: () => (
              <TouchableOpacity onPress={onLogout} style={styles.logoutBtn}>
                <MaterialCommunityIcons name="logout" size={20} color="#818cf8" />
                <Text style={styles.logoutText}>Logout</Text>
              </TouchableOpacity>
            ),
          }}
        >
          {/* Pass onLogout so PatientListScreen can use it if needed */}
          {props => <PatientListScreen {...props} />}
        </Stack.Screen>

        <Stack.Screen
          name="PatientDetail"
          options={({ route }) => ({ title: route.params.patient.name })}
          component={PatientDetailScreen}
        />
      </Stack.Navigator>
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
