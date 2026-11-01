import { useEffect, useState } from 'react';
import { AccessibilityInfo, Animated, DimensionValue, Easing, StyleSheet } from 'react-native';

import { colors, radius } from '@/theme/tokens';

type Props = { width?: DimensionValue; height?: number; round?: boolean };

/** A placeholder with the shape of the coming content. Holds still when Reduce Motion is on. */
export function Skeleton({ width = '100%', height = 16, round }: Props) {
  const [opacity] = useState(() => new Animated.Value(0.55));
  useEffect(() => {
    let loop: Animated.CompositeAnimation | null = null;
    let active = true;
    void AccessibilityInfo.isReduceMotionEnabled()
      .catch(() => true)
      .then((reduced) => {
        if (!active || reduced) return;
        const step = (toValue: number) =>
          Animated.timing(opacity, {
            toValue,
            duration: 700,
            easing: Easing.inOut(Easing.quad),
            useNativeDriver: true,
          });
        loop = Animated.loop(Animated.sequence([step(1), step(0.55)]));
        loop.start();
      });
    return () => {
      active = false;
      loop?.stop();
    };
  }, [opacity]);
  return (
    <Animated.View
      accessibilityElementsHidden
      importantForAccessibility="no"
      style={[styles.block, { width, height, opacity, borderRadius: round ? height / 2 : radius.xs }]}
    />
  );
}

const styles = StyleSheet.create({ block: { backgroundColor: colors.field } });
