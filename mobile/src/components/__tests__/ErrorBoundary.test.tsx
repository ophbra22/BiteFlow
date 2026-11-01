import AsyncStorage from '@react-native-async-storage/async-storage';
import { fireEvent, render } from '@testing-library/react-native';
import { Text } from 'react-native';
import { Try } from 'expo-router/build/views/Try';
import { ErrorBoundary } from '../ErrorBoundary';

jest.mock('react-native-safe-area-context', () => jest.requireActual('react-native-safe-area-context/jest/mock').default);
jest.mock('expo-localization', () => ({ getLocales: () => [{ languageCode: 'en' }] }));
jest.mock('expo-router/build/views/Splash', () => ({ hideAsync: jest.fn() }));
jest.mock('expo-splash-screen', () => ({ hideAsync: jest.fn(() => Promise.resolve()) }));

beforeEach(async () => {
  await AsyncStorage.clear();
  // React reports intentionally thrown render errors in development.
  jest.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => jest.restoreAllMocks());

test.each([
  { language: 'en', title: 'Something went wrong', button: 'Try again', direction: 'ltr', align: 'left' },
  { language: 'he', title: 'משהו השתבש', button: 'נסו שוב', direction: 'rtl', align: 'right' },
] as const)('render failure recovers in $language with correct direction', async ({ language, title, button, direction, align }) => {
  await AsyncStorage.setItem('fl:v1:app:language', JSON.stringify(language));
  let shouldCrash = true;
  function Content() {
    if (shouldCrash) throw new Error('private diagnostic information');
    return <Text>Recovered content</Text>;
  }
  // Exercise the same SDK 57 boundary wrapper used for route exports.
  const view = await render(<Try catch={ErrorBoundary}><Content /></Try>);
  const heading = view.getByText(title, { exact: false });
  expect(heading).toHaveStyle({ textAlign: align, writingDirection: direction });
  expect(view.getByTestId('crash-recovery')).toHaveStyle({ direction });
  expect(view.queryByText('private diagnostic information')).toBeNull();
  shouldCrash = false;
  await fireEvent.press(view.getByRole('button', { name: new RegExp(button) }));
  expect(view.getByText('Recovered content')).toBeTruthy();
  expect(view.queryByTestId('crash-recovery')).toBeNull();
});

test('a persistent render error remains recoverable after retry', async () => {
  function Broken(): never { throw new Error('still broken'); }
  const view = await render(<Try catch={ErrorBoundary}><Broken /></Try>);
  await fireEvent.press(view.getByRole('button', { name: 'Try again' }));
  expect(view.getByText('Something went wrong')).toBeTruthy();
  expect(view.getByRole('button', { name: 'Try again' })).toBeEnabled();
});

test('storage failure does not prevent recovery UI or expose the diagnostic', async () => {
  jest.spyOn(AsyncStorage, 'getItem').mockRejectedValue(new Error('storage unavailable'));
  function Broken(): never { throw new Error('private diagnostic'); }
  const view = await render(<Try catch={ErrorBoundary}><Broken /></Try>);
  expect(view.getByRole('button', { name: 'Try again' })).toBeTruthy();
  expect(view.queryByText('private diagnostic')).toBeNull();
});

test('healthy content renders without recovery UI', async () => {
  const view = await render(<Try catch={ErrorBoundary}><Text>Healthy</Text></Try>);
  expect(view.getByText('Healthy')).toBeTruthy();
  expect(view.queryByTestId('crash-recovery')).toBeNull();
});