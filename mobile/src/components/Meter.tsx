import { StyleSheet, View, ViewProps } from 'react-native';

import { colors } from '@/theme/tokens';

type Props = ViewProps & {
  /** 0 to 100. Larger values fill the track; the text beside it carries the real figure. */
  percent: number;
  color?: string;
  height?: number;
};

/** A progress bar that fills from the reading edge in both directions. */
export function Meter({ percent, color = colors.sage, height = 8, style, ...rest }: Props) {
  const width = Math.max(0, Math.min(100, percent));
  return (
    <View {...rest} style={[styles.track, { height, borderRadius: height / 2 }, style]}>
      <View style={{ width: `${width}%`, height, borderRadius: height / 2, backgroundColor: color }} />
    </View>
  );
}

const styles = StyleSheet.create({
  track: { overflow: 'hidden', backgroundColor: colors.field, alignSelf: 'stretch' },
});
