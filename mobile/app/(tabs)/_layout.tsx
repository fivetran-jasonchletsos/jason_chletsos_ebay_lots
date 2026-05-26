import { Feather } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import { Tabs } from 'expo-router';
import React from 'react';
import { Platform, StyleSheet, View } from 'react-native';

import { HapticTab } from '@/components/haptic-tab';
import { theme, fonts } from '@/src/theme';

type FeatherName = React.ComponentProps<typeof Feather>['name'];

function TabIcon({ name, focused }: { name: FeatherName; focused: boolean }) {
  return (
    <View style={{ alignItems: 'center', justifyContent: 'center', width: 32, height: 26 }}>
      <Feather name={name} size={22} color={focused ? theme.gold : theme.textDim} />
    </View>
  );
}

/**
 * Frosted, gold-edged tab bar. Mirrors the web app header's blur + thin gold
 * underline so the brand stays consistent across surfaces.
 */
function TabBarBackground() {
  return (
    <View style={StyleSheet.absoluteFill}>
      <BlurView
        intensity={30}
        tint="dark"
        style={StyleSheet.absoluteFill}
      />
      {/* Solid backstop on Android (BlurView is iOS-strong) and to make the
          tab bar legible against bright product photos. */}
      <View
        style={[
          StyleSheet.absoluteFill,
          { backgroundColor: 'rgba(10,10,10,0.7)' },
        ]}
      />
      {/* 1px gold border on top — echoes the site's section-head underline. */}
      <View
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 1,
          backgroundColor: theme.gold,
          opacity: 0.45,
        }}
      />
    </View>
  );
}

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarButton: HapticTab,
        tabBarBackground: TabBarBackground,
        tabBarActiveTintColor: theme.gold,
        tabBarInactiveTintColor: theme.textDim,
        tabBarStyle: {
          // Transparent so the blur shows through; the background component
          // above paints the surface + gold rule.
          backgroundColor: 'transparent',
          borderTopWidth: 0,
          // Float the bar slightly on iOS — looks more like the web header.
          position: Platform.select({ ios: 'absolute', default: undefined }),
          elevation: 0,
        },
        tabBarLabelStyle: {
          fontFamily: fonts.bodyBold,
          fontSize: 10,
          letterSpacing: 1.2,
          textTransform: 'uppercase',
        },
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'Scan',
          tabBarIcon: ({ focused }) => <TabIcon name="camera" focused={focused} />,
        }}
      />
      <Tabs.Screen
        name="listings"
        options={{
          title: 'Listings',
          tabBarIcon: ({ focused }) => <TabIcon name="tag" focused={focused} />,
        }}
      />
      <Tabs.Screen
        name="offers"
        options={{
          title: 'Offers',
          tabBarIcon: ({ focused }) => <TabIcon name="mail" focused={focused} />,
        }}
      />
      <Tabs.Screen
        name="inventory"
        options={{
          title: 'Inventory',
          tabBarIcon: ({ focused }) => <TabIcon name="archive" focused={focused} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Settings',
          tabBarIcon: ({ focused }) => <TabIcon name="settings" focused={focused} />,
        }}
      />
    </Tabs>
  );
}
