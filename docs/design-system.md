# Orbit design system

FoodLogger (web) and BiteFlow (iOS and Android) share one brand: deep pine, warm sand, one sage action colour and Fredoka. The website keeps its values in `src/foodlogger/static/tokens.css`. The app keeps the same values in `mobile/src/theme/tokens.ts`.

## Colour

| Role | App token | Web token | Value |
| --- | --- | --- | --- |
| Screen background | `ground` | `--color-paper` | `#14251D` |
| Cards and panels | `surface` | `--color-paper-2` | `#1E3529` |
| Inputs and secondary buttons | `field` | `--color-paper-3` | `#294536` |
| Hairlines | `line` | `--color-rule` | `#2F4D3D` |
| Field edge | `fieldEdge` | `--color-field-edge` | `#7A9484` |
| Primary text | `sand` | `--color-ink` | `#EFE6D3` |
| Quiet text | `muted` | `--color-muted` | `#A8B6A6` |
| Primary action | `sage` | `--color-accent` | `#A3C29F` |
| Warnings | `butter` | `--color-butter` | `#E8D48B` |
| Errors and destructive actions | `danger` | `--color-danger` | `#F2A99D` |

Colour has one meaning everywhere:

- **Macros:** protein is sage, carbohydrates are butter, fat is rose.
- **Meals:** breakfast is butter, lunch is sage, dinner is lilac, a snack is rose.

Each state also has a word or an icon, so colour is never the only signal.

## Shared patterns

| Pattern | App | Website |
| --- | --- | --- |
| Day dial | `DayDial`: 24-hour ring with meal dots, total and add button at its centre | `#day-dial`: the same ring and geometry, with the total at its centre |
| Macro summary | `MacroSummary`: against a goal when one is set, otherwise share of energy | Share of logged energy |
| Journal | Grouped by meal, one card per group | Grouped by meal, hairlines inside one panel |
| Choosing a method | Lead action and tiles, then a grouped list | Segmented tabs: photo, barcode, values |
| Feedback | `Notice`, `Toast`, `EmptyState`, `Skeleton` | Inline messages, `.toast`, `.empty-state`, a loading placeholder |
| Navigation | Native stack and modal | Sticky top bar; a fixed log action on small screens |

Components stay native to each platform. The website has no equivalent of the app's stack navigation, and the app does not use the website's tabs.

## Rules for both

- One primary action per view.
- Panels are never nested. Rows inside a panel are separated by hairlines.
- A missing nutrient is written out and never shown as 0.
- Touch targets are at least 44 points on the web and 48 in the app.
- Motion is limited to press feedback, the toast and the loading placeholder, and it respects Reduce Motion.
- Layout uses logical direction: the app mirrors for Hebrew through the language setting, and the website's CSS uses logical properties. The website has no Hebrew text yet. The dial and codes do not mirror.

## Type and space

Fredoka covers Latin and Hebrew. The website serves it from `src/foodlogger/static/`, so the content security policy needs no outside font host. Spacing follows 4, 8, 12, 16, 24 and 32. Panels use a 22 radius, fields 12, and buttons a pill.
