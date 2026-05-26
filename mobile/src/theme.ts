// Dark-luxe palette — matches the web scanner so the brand stays consistent
// across phone + browser.

export const theme = {
  bg:          '#0a0a0a',
  surface:     '#141414',
  surface2:    '#1a1a1a',
  surface3:    '#232323',
  border:      'rgba(201,165,66,0.10)',
  borderMid:   'rgba(201,165,66,0.22)',
  borderHi:    'rgba(201,165,66,0.45)',
  gold:        '#c9a542',
  goldBright:  '#e6c66a',
  goldDim:     '#8a7521',
  text:        '#f1efe9',
  textMuted:   '#9a9388',
  textDim:     '#5d574c',
  success:     '#7fc77a',
  warning:     '#e0b54a',
  danger:      '#e07b6f',
  // Site links use gold rather than the generic OS blue. Keeps the palette
  // tight and matches the web build.
  link:        '#c9a542',
} as const;

export const radii = {
  sm: 6,
  md: 10,
  lg: 16,
  xl: 22,
} as const;

// Font family tokens. These names must match what `useFonts()` registers in
// `mobile/app/_layout.tsx` (Stream C owns that hookup):
//   @expo-google-fonts/fraunces        -> Fraunces_500Italic
//   @expo-google-fonts/familjen-grotesk -> FamiljenGrotesk_{400,500,600,700}
export const fonts = {
  display:  'Fraunces_500Italic',
  body:     'FamiljenGrotesk_400Regular',
  bodyMed:  'FamiljenGrotesk_500Medium',
  bodyBold: 'FamiljenGrotesk_700Bold',
  // JetBrains Mono is optional — if the bundle ever ships it under
  // JetBrainsMono_400Regular this will pick it up. Until then RN falls back
  // to the platform monospace, which is fine for the very few mono usages.
  mono:     'JetBrainsMono_400Regular',
} as const;
