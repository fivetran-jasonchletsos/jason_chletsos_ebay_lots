import { DarkTheme, ThemeProvider } from '@react-navigation/native';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import 'react-native-reanimated';

import { theme } from '@/src/theme';
import { getDb } from '@/src/db';
import { ensureCardsDir } from '@/src/image-store';

const navTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: theme.bg,
    card: theme.bg,
    text: theme.text,
    border: theme.border,
    primary: theme.gold,
  },
};

export const unstable_settings = {
  anchor: '(tabs)',
};

export default function RootLayout() {
  useEffect(() => {
    // Warm up the DB + image store on app launch.
    getDb().catch((e) => console.error('DB init', e));
    ensureCardsDir().catch((e) => console.error('Image store init', e));
  }, []);

  return (
    <ThemeProvider value={navTheme}>
      <Stack screenOptions={{ contentStyle: { backgroundColor: theme.bg } }}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen
          name="card/[id]"
          options={{
            title: '',
            headerStyle: { backgroundColor: theme.bg },
            headerTintColor: theme.gold,
          }}
        />
      </Stack>
      <StatusBar style="light" />
    </ThemeProvider>
  );
}
