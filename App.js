import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { SleepProvider } from './context/SleepContext';

import HomeScreen    from './screens/HomeScreen';
import AlertsScreen  from './screens/AlertsScreen';
import ReportScreen  from './screens/ReportScreen';
import NetworkScreen from './screens/NetworkScreen';

const Tab = createBottomTabNavigator();

export default function App() {
  return (
    <SafeAreaProvider>
      <SleepProvider>
        <NavigationContainer>
          <Tab.Navigator
            screenOptions={{
              headerShown: false,
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
            <Tab.Screen name="Home"    component={HomeScreen}    />
            <Tab.Screen name="Alerts"  component={AlertsScreen}  />
            <Tab.Screen name="Report"  component={ReportScreen}  />
            <Tab.Screen name="Network" component={NetworkScreen} />
          </Tab.Navigator>
        </NavigationContainer>
      </SleepProvider>
    </SafeAreaProvider>
  );
}