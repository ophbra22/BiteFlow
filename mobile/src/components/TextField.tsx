import { useState } from 'react';
import { Pressable, StyleSheet, TextInput, TextInputProps, View } from 'react-native';

import { useI18n } from '@/i18n/I18nProvider';
import { colors, fonts, radius, spacing, touch } from '@/theme/tokens';

import { AppText } from './AppText';
import { Icon } from './Icon';

type Props = Omit<TextInputProps, 'style'> & {
  label: string;
  hint?: string;
  /** Translated problem to show under the field. */
  error?: string | null;
  /** Unit shown after the value, such as "g" or "kcal". */
  suffix?: string;
  /** Usernames, passwords, codes and numbers read left-to-right in every language. */
  ltr?: boolean;
  /** Adds a show/hide control for passwords. */
  secret?: boolean;
  required?: boolean;
};

export function TextField({ label, hint, error, suffix, ltr, secret, required, ...input }: Props) {
  const { t } = useI18n();
  const [focused, setFocused] = useState(false);
  const [hidden, setHidden] = useState(true);
  const description = [required ? t('a11y.required') : null, error ?? hint].filter(Boolean).join('. ');
  return (
    <View style={styles.wrap}>
      <AppText variant="label" color={colors.muted}>
        {label}
        {required ? ' *' : ''}
      </AppText>
      <View style={[styles.box, focused && styles.focused, !!error && styles.invalid]}>
        <TextInput
          {...input}
          accessibilityLabel={label}
          accessibilityHint={description || undefined}
          secureTextEntry={secret ? hidden : input.secureTextEntry}
          placeholderTextColor={colors.muted}
          selectionColor={colors.sage}
          cursorColor={colors.sage}
          maxFontSizeMultiplier={1.6}
          onFocus={(event) => {
            setFocused(true);
            input.onFocus?.(event);
          }}
          onBlur={(event) => {
            setFocused(false);
            input.onBlur?.(event);
          }}
          style={[
            styles.input,
            ltr ? styles.ltr : styles.natural,
            input.multiline && styles.multiline,
          ]}
        />
        {suffix ? (
          <AppText variant="label" color={colors.muted}>
            {suffix}
          </AppText>
        ) : null}
        {secret ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={hidden ? t('auth.showPassword') : t('auth.hidePassword')}
            hitSlop={10}
            onPress={() => setHidden((value) => !value)}
            style={styles.eye}>
            <Icon name={hidden ? 'eye' : 'eye-off'} color={colors.muted} size={20} />
          </Pressable>
        ) : null}
      </View>
      {error ? (
        <AppText variant="caption" color={colors.danger} accessibilityLiveRegion="polite">
          {error}
        </AppText>
      ) : hint ? (
        <AppText variant="caption" color={colors.muted}>
          {hint}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xs + 2 },
  box: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    minHeight: 56,
    borderRadius: radius.md,
    borderWidth: 1.5,
    borderColor: colors.fieldEdge,
    backgroundColor: colors.field,
    paddingHorizontal: spacing.lg,
  },
  focused: { borderColor: colors.sage },
  invalid: { borderColor: colors.danger },
  input: {
    flex: 1,
    minHeight: touch,
    paddingVertical: spacing.sm,
    fontFamily: fonts.regular,
    fontSize: 18,
    color: colors.sand,
  },
  // No fixed alignment: the platform starts typed text at the reading edge of its own script.
  natural: {},
  ltr: { writingDirection: 'ltr', textAlign: 'left' },
  multiline: { minHeight: 80, textAlignVertical: 'top' },
  eye: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },
});
