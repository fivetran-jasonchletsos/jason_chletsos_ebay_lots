import { Tabs } from 'expo-router';
import React from 'react';
import { Text, View } from 'react-native';

import { HapticTab } from '@/components/haptic-tab';
import { theme } from '@/src/theme';

function TabIcon({ glyph, focused }: { glyph: string; focused: boolean }) {
  return (
    <View style={{ alignItems: 'center', justifyContent: 'center', width: 32 }}>
      <Text style={{ fontSize: 22, color: focused ? theme.gold : theme.textDim, lineHeight: 26 }}>{glyph}</Text>
    </View>
  );
}

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarButton: HapticTab,
        tabBarActiveTintColor: theme.gold,
        tabBarInactiveTintColor: theme.textDim,
        tabBarStyle: {
          backgroundColor: theme.surface,
          borderTopColor: theme.border,
          borderTopWidth: 1,
        },
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: '700',
          letterSpacing: 1.2,
          textTransform: 'uppercase',
        },
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'Scan',
          tabBarIcon: ({ focused }) => <TabIcon glyph="📷" focused={focused} />,
        }}
      />
      <Tabs.Screen
        name="inventory"
        options={{
          title: 'Inventory',
          tabBarIcon: ({ focused }) => <TabIcon glyph="🗂" focused={focused} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Settings',
          tabBarIcon: ({ focused }) => <TabIcon glyph="⚙" focused={focused} />,
        }}
      />
    </Tabs>
  );
}
