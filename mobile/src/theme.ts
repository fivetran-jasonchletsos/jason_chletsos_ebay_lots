// Dark-luxe palette — matches the web scanner so the brand stays consistent
// across phone + browser.

export const theme = {
  bg:          '#0a0a0a',
  surface:     '#141414',
  surface2:    '#1a1a1a',
  surface3:    '#232323',
  border:      'rgba(212,175,55,0.10)',
  borderMid:   'rgba(212,175,55,0.22)',
  borderHi:    'rgba(212,175,55,0.45)',
  gold:        '#d4af37',
  goldBright:  '#f4ce5d',
  goldDim:     '#8a7521',
  text:        '#f1efe9',
  textMuted:   '#9a9388',
  textDim:     '#5d574c',
  success:     '#7fc77a',
  warning:     '#e0b54a',
  danger:      '#e07b6f',
  link:        '#6cb0ff',
} as const;

export const radii = {
  sm: 6,
  md: 10,
  lg: 16,
  xl: 22,
} as const;

export const fonts = {
  display: 'Bebas Neue',
  body: 'Inter',
  mono: 'JetBrains Mono',
} as const;
