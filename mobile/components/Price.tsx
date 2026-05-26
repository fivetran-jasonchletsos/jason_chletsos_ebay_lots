/**
 * Shared price display — Fraunces italic in the gold-bright accent.
 *
 * One component so every dollar amount on the app — listings row, listing
 * detail, offer compare cells — reads with the same brand voice. Pass a
 * numeric `value`; the component handles the `$` glyph + two-decimal format
 * + em-dash fallback when null/undefined.
 */
import { StyleSheet, Text, TextStyle, View, ViewStyle } from 'react-native';

import { fonts, theme } from '@/src/theme';

export type PriceSize = 'sm' | 'md' | 'lg' | 'xl';

interface PriceProps {
  value: number | null | undefined;
  size?: PriceSize;
  /**
   * Tone hint:
   *   "default"  — bright gold (lists, headers, main accent)
   *   "muted"    — main text color (secondary compare cells)
   *   "danger"   — warm red (negative deltas)
   */
  tone?: 'default' | 'muted' | 'danger';
  style?: ViewStyle;
  textStyle?: TextStyle;
}

const SIZE_PX: Record<PriceSize, number> = {
  sm: 14,
  md: 18,
  lg: 24,
  xl: 32,
};

export function Price({
  value,
  size = 'md',
  tone = 'default',
  style,
  textStyle,
}: PriceProps) {
  const text = value == null ? '—' : `$${value.toFixed(2)}`;
  const color =
    tone === 'muted'
      ? theme.text
      : tone === 'danger'
        ? theme.danger
        : theme.goldBright;

  return (
    <View style={[styles.wrap, style]}>
      <Text
        style={[
          styles.text,
          { fontSize: SIZE_PX[size], color },
          textStyle,
        ]}
      >
        {text}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    alignItems: 'baseline',
  },
  text: {
    // Fraunces italic — distinctive, editorial, very-not-AI-aesthetic. Letter-
    // spacing left at 0 so the italic carries the visual weight.
    fontFamily: fonts.display,
    letterSpacing: 0,
  },
});

export default Price;
