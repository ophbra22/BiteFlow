/**
 * Orbit design system: a deep pine ground, sand text, and one soft tint per meal.
 * Every colour, size and radius in the app comes from here.
 */
import { Platform, TextStyle } from 'react-native';

import type { MealType } from '@/domain/nutrition';

export const colors = {
  /** Screen background. */
  ground: '#14251D',
  /** Cards, rows and sheets. */
  surface: '#1E3529',
  /** Inputs and pressed states. */
  field: '#294536',
  /** Hairlines between quiet areas. */
  line: '#2F4D3D',
  /** Quiet fills behind icons and tinted notices. */
  sageTint: 'rgba(163, 194, 159, 0.16)',
  butterTint: 'rgba(232, 212, 139, 0.12)',
  dangerTint: 'rgba(242, 169, 157, 0.12)',
  /** Primary text. */
  sand: '#EFE6D3',
  /** Secondary text. 6.9:1 on ground, 5.5:1 on surface. */
  muted: '#A8B6A6',
  /** The accent: the add button and every primary action. */
  sage: '#A3C29F',
  /** Text and icons on sage. */
  onSage: '#14251D',
  butter: '#E8D48B',
  lilac: '#BCA9DC',
  rose: '#E3A6A0',
  /** Errors and destructive actions. */
  danger: '#F2A99D',
  onDanger: '#3A1510',
  scrim: 'rgba(8, 16, 12, 0.6)',
} as const;

/** One tint per meal, used for the dial dots and the list markers. */
export const mealColors: Record<MealType, string> = {
  breakfast: colors.butter,
  lunch: colors.sage,
  dinner: colors.lilac,
  snack: colors.rose,
};

/** The same three macro colours on every screen and chart. */
export const macroColors = {
  protein: colors.sage,
  carbs: colors.butter,
  fat: colors.rose,
} as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, xxxl: 48 } as const;

export const radius = { xs: 8, sm: 12, md: 18, lg: 22, xl: 30, pill: 999 } as const;

/** Smallest comfortable touch target on both platforms. */
export const touch = 48;

/** Press feedback and short transitions. Longer motion is not part of this system. */
export const motion = { fast: 140, base: 220 } as const;

/** Readable column on large screens; phones use the full width. */
export const contentWidth = 640;

export const fonts = {
  regular: 'Fredoka_400Regular',
  medium: 'Fredoka_500Medium',
  semibold: 'Fredoka_600SemiBold',
  /** Fixed-width system face for codes that must be copied exactly (l, I, 0 and O stay distinct). */
  mono: Platform.select({ ios: 'Menlo', default: 'monospace' }),
} as const;

/** The type scale. Sizes grow with the system text size setting. */
export const type: Record<string, TextStyle> = {
  display: { fontFamily: fonts.semibold, fontSize: 52, lineHeight: 58, fontVariant: ['tabular-nums'] },
  /** A headline value inside a card: daily calories in the dial, a meal's total. */
  figure: { fontFamily: fonts.semibold, fontSize: 38, lineHeight: 44, fontVariant: ['tabular-nums'] },
  title: { fontFamily: fonts.semibold, fontSize: 28, lineHeight: 34 },
  heading: { fontFamily: fonts.semibold, fontSize: 20, lineHeight: 26 },
  body: { fontFamily: fonts.regular, fontSize: 17, lineHeight: 24 },
  bodyStrong: { fontFamily: fonts.medium, fontSize: 17, lineHeight: 24 },
  label: { fontFamily: fonts.medium, fontSize: 15, lineHeight: 20 },
  caption: { fontFamily: fonts.regular, fontSize: 14, lineHeight: 19 },
  number: { fontFamily: fonts.semibold, fontSize: 19, lineHeight: 24, fontVariant: ['tabular-nums'] },
  /** Section titles inside a screen, one step above body. */
  section: { fontFamily: fonts.semibold, fontSize: 18, lineHeight: 24 },
} as const;

export type TypeVariant = keyof typeof type;
