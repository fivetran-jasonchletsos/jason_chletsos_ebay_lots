import { DarkTheme, ThemeProvider } from '@react-navigation/native';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import { View } from 'react-native';
import 'react-native-reanimated';

import {
  useFonts,
  Fraunces_500Medium_Italic,
} from '@expo-google-fonts/fraunces';
import {
  FamiljenGrotesk_400Regular,
  FamiljenGrotesk_500Medium,
  FamiljenGrotesk_700Bold,
} from '@expo-google-fonts/familjen-grotesk';

import { theme } from '@/src/theme';
import { getDb } from '@/src/db';
import { ensureCardsDir } from '@/src/image-store';

// Keep the splash up until fonts load so we never flash unstyled text. This
// runs at module scope so it's set before any screen renders.
SplashScreen.preventAutoHideAsync().catch(() => {
  /* already hidden — fine */
});

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
  // Note: theme.fonts.display is `Fraunces_500Italic` (Stream B's contract),
  // but the upstream package exports it as `Fraunces_500Medium_Italic`. We
  // register the loaded font under the theme-expected alias so callers can
  // use `fonts.display` without caring about the upstream rename.
  const [fontsLoaded, fontError] = useFonts({
    Fraunces_500Italic: Fraunces_500Medium_Italic,
    FamiljenGrotesk_400Regular,
    FamiljenGrotesk_500Medium,
    FamiljenGrotesk_700Bold,
  });

  useEffect(() => {
    // Warm up the DB + image store on app launch.
    getDb().catch((e) => console.error('DB init', e));
    ensureCardsDir().catch((e) => console.error('Image store init', e));
  }, []);

  useEffect(() => {
    // Hide splash once fonts resolve (success OR failure — we don't want to
    // hang the app on a font 404).
    if (fontsLoaded || fontError) {
      SplashScreen.hideAsync().catch(() => { /* noop */ });
    }
  }, [fontsLoaded, fontError]);

  if (!fontsLoaded && !fontError) {
    // Render nothing until fonts are ready. Splash is still up.
    return <View style={{ flex: 1, backgroundColor: theme.bg }} />;
  }

  return (
    <ThemeProvider value={navTheme}>
      <Stack screenOptions={{ contentStyle: { backgroundColor: theme.bg } }}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen
          name="card/[id]/index"
          options={{
            title: '',
            headerStyle: { backgroundColor: theme.bg },
            headerTintColor: theme.gold,
          }}
        />
        <Stack.Screen
          name="card/[id]/list-on-ebay"
          options={{
            title: 'List on eBay',
            presentation: 'modal',
            headerStyle: { backgroundColor: theme.bg },
            headerTintColor: theme.gold,
          }}
        />
        <Stack.Screen
          name="listing/[itemId]/index"
          options={{
            title: '',
            headerStyle: { backgroundColor: theme.bg },
            headerTintColor: theme.gold,
          }}
        />
        <Stack.Screen
          name="listing/[itemId]/replace-photos"
          options={{
            title: 'Replace photos',
            presentation: 'modal',
            headerStyle: { backgroundColor: theme.bg },
            headerTintColor: theme.gold,
          }}
        />
        <Stack.Screen
          name="quick-list"
          options={{
            title: 'Quick list',
            presentation: 'modal',
            headerStyle: { backgroundColor: theme.bg },
            headerTintColor: theme.gold,
          }}
        />
      </Stack>
      <StatusBar style="light" />
    </ThemeProvider>
  );
}
