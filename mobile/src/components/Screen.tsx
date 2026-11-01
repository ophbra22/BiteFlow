import { ReactNode, createContext, useContext, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  RefreshControlProps,
  ScrollView,
  StyleSheet,
  View,
  useWindowDimensions,
} from 'react-native';
import { Edge, SafeAreaView } from 'react-native-safe-area-context';

import { colors, contentWidth, spacing } from '@/theme/tokens';

/**
 * True for screens shown inside the "add a meal" modal. On iOS that modal is a
 * sheet that already starts below the status bar, so the top safe-area inset
 * must not be added a second time.
 */
export const SheetContext = createContext(false);

type Props = {
  children: ReactNode;
  /** Fixed above the scrolling content. */
  header?: ReactNode;
  /** Fixed below the scrolling content; stays above the keyboard. */
  footer?: ReactNode;
  scroll?: boolean;
  refreshControl?: React.ReactElement<RefreshControlProps>;
  edges?: Edge[];
  padded?: boolean;
};

/** Page frame: safe areas, the pine ground, and content that moves out of the keyboard's way. */
export function Screen({
  children,
  header,
  footer,
  scroll = true,
  refreshControl,
  edges,
  padded = true,
}: Props) {
  const { height: windowHeight } = useWindowDimensions();
  const [keyboardOffset, setKeyboardOffset] = useState(0);
  // Fabric needs the native scroll view mounted before attaching UIRefreshControl.
  const [scrollReady, setScrollReady] = useState(false);
  const inSheet = useContext(SheetContext);
  const safeEdges: Edge[] =
    edges ?? (inSheet && Platform.OS === 'ios' ? ['bottom', 'left', 'right'] : ['top', 'bottom', 'left', 'right']);
  const body = scroll ? (
    <ScrollView
      testID="screen-scroll"
      style={styles.flex}
      contentContainerStyle={[styles.content, styles.column, padded && styles.padded]}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
      onLayout={() => setScrollReady(true)}
      refreshControl={scrollReady ? refreshControl : undefined}
      showsVerticalScrollIndicator={false}>
      {children}
    </ScrollView>
  ) : (
    <View style={[styles.flex, styles.column, padded && styles.padded]}>{children}</View>
  );
  return (
    <SafeAreaView style={styles.safe} edges={safeEdges}
      onLayout={({ nativeEvent }) => {
        // iOS measures a page sheet in its own coordinate space (y = 0),
        // while keyboard events use the full screen. Its missing height is
        // the sheet's top offset. Orientation is portrait in this app.
        setKeyboardOffset(inSheet ? Math.max(0, windowHeight - nativeEvent.layout.height) : 0);
      }}>
      <KeyboardAvoidingView style={styles.flex} keyboardVerticalOffset={Platform.OS === 'ios' ? keyboardOffset : 0} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
        {header}
        {body}
        {footer ? <View style={[styles.footer, styles.column]}>{footer}</View> : null}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.ground },
  flex: { flex: 1 },
  // Keeps lines and cards at a readable width if the app runs on a wider screen.
  column: { width: '100%', maxWidth: contentWidth, alignSelf: 'center' },
  content: { flexGrow: 1, gap: spacing.lg, paddingBottom: spacing.xl },
  padded: { paddingHorizontal: spacing.lg },
  footer: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.md,
    gap: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
  },
});
