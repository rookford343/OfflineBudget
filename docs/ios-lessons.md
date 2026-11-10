# iOS lessons

Lessons for the future native iOS app, updated as the phone-on-home-network work proceeds.

## Passkeys on .local

Owner result, 2026-11-09: Safari on iPhone created and used a passkey with rp.id `df-macbookpro16.local` over the private-CA HTTPS with no warning. A wrong host name (`df-macbookpro.local`) loads but must not be used (a passkey is bound to the exact host). The home-screen (standalone) passkey test is still pending: record here whether create and get work there, with the exact error name and message for any failure.

## Duo viewport widths

Measured from the owner's iPhone screenshots (3x scale): folded is about 457px CSS wide, unfolded about 951px. Unfolded sits in Tailwind's `sm` to `lg` (640 to 1023) range, so it gets the phone-wide layout, not the desktop one. The status bar sits on one side of the screen, so the safe-area inset there must be painted with the page background (html/body, theme-color) and content must respect `env(safe-area-inset-left/right)`.

## Forecast, Recurring and Spending at phone widths

Layout only, below `lg` (1024px). Measured on a loopback demo build at 390, 700 and 1280 wide; no page-level horizontal scroll at 390 or 700 on any page.

- **Forecast.** 390: the chart's x-axis labels collided (a label every few days), so show every third tick and shrink the chart from 280 to 240 high; the hover-only "set balance / add transaction" icons in the quarter detail were invisible on touch, so they are always shown and padded to a finger-sized target. 700: nothing needed beyond the tap targets. The header selects already wrap. The quarter-detail table already scrolled sideways inside its own box.
- **Recurring.** 390: item rows let the name and badges squeeze the amount and icons, so the name column now shrinks and the badges wrap; icon buttons got 44px targets. 700: fine as it was. Long names still truncate on a few cards by design.
- **Spending.** 390: the three stat cards (Discretionary, Fixed, Total) forced the whole main column to scroll sideways (409px in 390), so they stack below 640. The Mo/3 Mo/YTD/Last Yr chips, tabs and date inputs got 44px targets, and the merchant rename pencil is always visible (it was hover-only). The Sankey sits in a sideways scroller with a 640px minimum width below 640. 700: fine as it was.
- A shared `tap-44` class (index.css) gives `.input` and `.btn*` controls a 44px minimum height below `lg`; pages opt in. The `useMinWidth` hook moved to `frontend/src/lib/useMinWidth.ts`.
- What the owner actually used on the Duo (folded and unfolded): pending, recorded at the cutover session.

## Later

- Mark pending rows as today in the phone Dashboard's recent transactions. The `/spending/recent` feed carries no pending flag, so this needs backend work first.
