# Orbit design system

BiteFlow and the FoodLogger website share one brand: deep pine, warm sand, one sage action colour and Fredoka. This file records the rules; `tokens.ts` holds the values for the app and `static/style.css` holds the same values for the website.

## Colour

| Role | Token | Value | Use |
| --- | --- | --- | --- |
| Ground | `ground` | `#14251D` | Screen background |
| Surface | `surface` | `#1E3529` | Cards and grouped lists |
| Field | `field` | `#294536` | Inputs, secondary buttons, pressed rows, meter tracks |
| Line | `line` | `#2F4D3D` | Hairlines |
| Text | `sand` | `#EFE6D3` | Primary text |
| Quiet text | `muted` | `#A8B6A6` | Secondary text |
| Action | `sage` / `onSage` | `#A3C29F` / `#14251D` | The one primary action per view |
| Attention | `butter` | `#E8D48B` | Warnings |
| Error | `danger` / `onDanger` | `#F2A99D` / `#3A1510` | Errors and destructive actions |

Colour carries a fixed meaning on every screen and chart:

- **Macros:** protein is sage, carbohydrates are butter, fat is rose.
- **Meals:** breakfast is butter, lunch is sage, dinner is lilac, a snack is rose.
- **Charts:** logged values are sage, the goal is a butter line, weight is rose.

Each state also has a word or an icon, so colour is never the only signal.

## Type

Fredoka covers Latin and Hebrew. The scale is `display` 52, `figure` 38, `title` 28, `heading` 20, `section` 18, `body` 17, `label` 15 and `caption` 14. Numbers use tabular digits. Text grows with the system setting, up to 1.8×; `display` stops at 1.3×.

## Space and shape

- **Spacing:** 4, 8, 12, 16, 24, 32 and 48.
- **Radius:** 8, 12, 18, 22 and 30, plus the pill for buttons and chips.
- **Touch:** every target is at least 48 points, including hit slop.

## Components

| Need | Component |
| --- | --- |
| Actions | `Button` (primary, secondary, ghost, danger), `IconButton`, `Chip` |
| Choices | `Segmented` up to three inline, four as a 2×2 grid; `Chip` with `radio` for longer sets |
| Input | `TextField` with its label, hint, error, unit and show-password control |
| Structure | `Screen`, `Header`, `Section`, `Card`, `ListRow`, `Disclosure` |
| Progress | `Meter`, `MacroSummary`, `DayDial` |
| Feedback | `Notice` (info, success, warning, error), `Toast`, `EmptyState`, `Skeleton` |

## Behaviour

- One primary button per view. On long forms it sits in the fixed footer, above the keyboard.
- Cards are never nested. Group rows with hairlines inside one card.
- Options that few people need go inside a `Disclosure`.
- A missing nutrient reads as "Not provided". It is never shown as 0.
- Motion is limited to press feedback, the toast and loading placeholders. Reduce Motion stops the placeholder pulse.
- Haptics are limited to a selection, a small confirmed action, a finished task and a warning.

## Direction

The layout mirrors for Hebrew through the existing language setting. Clocks, charts and codes do not mirror: `DayDial` and `TrendsChart` keep their geometry, and usernames, barcodes and numbers stay left to right inside Hebrew text.
