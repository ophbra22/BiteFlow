import { StyleSheet, View } from 'react-native';

import { addDays } from '@/domain/dates';
import { useI18n } from '@/i18n/I18nProvider';
import { formatDay, formatFullDay, relativeDayLabel } from '@/i18n/format';
import { haptics } from '@/native/haptics';
import { colors, spacing } from '@/theme/tokens';

import { AppText } from './AppText';
import { directional } from './Icon';
import { IconButton } from './IconButton';

type Props = { day: string; onChange: (day: string) => void; compact?: boolean };

/** Previous / next day. The arrows follow the reading direction: "previous" is at the start. */
export function DayNav({ day, onChange, compact }: Props) {
  const { t, language } = useI18n();
  const step = (delta: number) => {
    haptics.selection();
    onChange(addDays(day, delta));
  };
  return (
    <View style={styles.row}>
      <IconButton icon={directional.back} label={t('dates.previousDay')} onPress={() => step(-1)} />
      <View
        style={styles.label}
        accessible
        accessibilityRole="header"
        accessibilityLiveRegion="polite"
        accessibilityLabel={`${relativeDayLabel(language, day)}, ${formatFullDay(language, day)}`}>
        <AppText variant={compact ? 'bodyStrong' : 'heading'} center numberOfLines={1}>
          {relativeDayLabel(language, day)}
        </AppText>
        <AppText variant="caption" color={colors.muted} center numberOfLines={1}>
          {formatDay(language, day)}
        </AppText>
      </View>
      <IconButton icon={directional.forward} label={t('dates.nextDay')} onPress={() => step(1)} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, flexShrink: 1 },
  label: { flexShrink: 1, minWidth: 96 },
});
