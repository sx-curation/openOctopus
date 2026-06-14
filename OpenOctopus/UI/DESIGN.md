# Design System Strategy: The Sovereign Architect

## 1. Overview & Creative North Star
The visual identity of this design system is anchored in the concept of **"The Sovereign Architect."** In the world of private banking, advisors do not just manage money; they architect legacies. This system rejects the cluttered, frantic energy of retail trading apps in favor of a poised, editorial experience that commands authority through restraint.

We move beyond the "standard SaaS" look by embracing **Asymmetric Balance** and **Negative Space as a Luxury.** By utilizing high-contrast typography scales and layered tonal depth, we create an environment that feels like a bespoke physical office—quiet, expensive, and hyper-organized. Every element is intentional; if a component doesn't serve a specific data-driven purpose, it is removed to preserve the "Sovereign" clarity required for high-net-worth portfolio management.

---

## 2. Colors: Tonal Architecture
The palette is built on a foundation of Deep Navy and Slate, utilizing the Material Design 3 token logic to create a sophisticated hierarchy.

### The "No-Line" Rule
**Explicit Instruction:** You are prohibited from using 1px solid borders to section off content. In this system, boundaries are defined strictly through background color shifts. To separate a sidebar from a main view, or a card from a background, use the transition from `surface` to `surface_container_low`. Lines create visual noise; tonal shifts create "zones" of focus.

### Surface Hierarchy & Nesting
Treat the UI as a series of physical layers—stacked sheets of fine stationery or frosted glass.
*   **Base Layer:** `surface` (#faf9fc) for the main application canvas.
*   **Secondary Layer:** `surface_container_low` (#f5f3f6) for sidebar navigation or secondary utility panels.
*   **Content Layer:** `surface_container_lowest` (#ffffff) for primary data cards. This creates a "lift" effect without needing heavy shadows.
*   **Active Layer:** `surface_container_high` (#e9e7eb) for recessed areas like search bars or inactive tabs.

### Signature Textures
*   **The Power Gradient:** Main CTAs or high-level wealth indicators should utilize a subtle linear gradient from `primary` (#000f27) to `primary_container` (#0b2447). This prevents the "flat" look and adds a professional sheen.
*   **Glassmorphism:** For floating tooltips and dropdown menus, use `surface_container_lowest` at 80% opacity with a `20px` backdrop-blur. This ensures the advisor never loses the context of the underlying data.

---

## 3. Typography: Editorial Authority
We pair **Manrope** (Display/Headlines) with **Inter** (Body/Data) to balance character with clinical precision.

*   **Display & Headlines (Manrope):** These are your "Statement" pieces. Use `display-lg` for total Net Worth or Portfolio AUM. The geometric nature of Manrope conveys modernity and stability.
*   **Body & Labels (Inter):** Inter is used for high-density data tables and sparkline labels. Its high x-height ensures legibility even at `label-sm` (11px).
*   **The Contrast Rule:** To achieve an editorial feel, pair very large `display-sm` numbers with very small `label-md` all-caps descriptions. This "High-Low" pairing is a hallmark of premium financial reporting.

---

## 4. Elevation & Depth: Tonal Layering
Traditional "drop shadows" are often a crutch for poor layout. In this system, depth is achieved through light and material density.

*   **The Layering Principle:** Instead of shadows, use the "Step" method. An inner card (`surface_container_lowest`) sits atop a section (`surface_container_low`) which sits on the global background (`surface`).
*   **Ambient Shadows:** If a component must float (e.g., a modal), use a "Long Shadow": `0px 24px 48px rgba(11, 36, 71, 0.06)`. The shadow color is a tinted version of our `on_surface` color, mimicking how light actually behaves in a room.
*   **The Ghost Border Fallback:** If accessibility requirements demand a container boundary, use a "Ghost Border": `outline_variant` (#c4c6cf) at **15% opacity**. It should be felt, not seen.

---

## 5. Components: Precision Primitives

### Cards & Data Containers
*   **Rule:** Forbid the use of divider lines within cards.
*   **Implementation:** Separate the card header from the body using a 24px vertical padding (from our Spacing Scale) or a subtle shift to `surface_container_low` for the header background. 
*   **Radius:** Use `lg` (0.5rem / 8px) for cards to maintain a crisp, professional edge.

### Synchronized Gauges & Sparklines
*   **Performance Visuals:** Use `on_primary_fixed` for neutral trends. 
*   **Semantic Accents:** `performance_green` (#10AC84) for growth and `performance_red` (#EE5253) for loss. Sparklines should have a 2px stroke width and use a subtle area-fill gradient (10% opacity) to ground them in the table cell.

### Interactive Tooltips
*   **Style:** Dark-themed using `inverse_surface` with `inverse_on_surface` text.
*   **Behavior:** 200ms delay on hover to avoid "flickering" as the advisor moves across dense data tables.

### Input Fields
*   **State:** Default state uses `surface_container_high` as a background rather than a border. On focus, transition the background to `surface_container_lowest` and apply a 1px "Ghost Border" of `primary`.

### Buttons
*   **Primary:** Solid `primary` (#000f27) with `on_primary` text. No border.
*   **Secondary:** `surface_container_highest` background with `on_surface` text.
*   **Tertiary:** Transparent background, `primary` text, no border. Used for low-priority actions to maintain the "Sovereign" hierarchy.

---

## 6. Do’s and Don’ts

### Do
*   **DO** use whitespace as a functional tool. If a screen feels "crowded," increase the padding between containers rather than adding lines.
*   **DO** align all data to a strict 8px grid. In fintech, alignment equals trust.
*   **DO** use `policy_gold` (#FF9F43) sparingly for high-value alerts or "Platinum" status indicators to maintain its prestige.

### Don’t
*   **DON'T** use pure black (#000000). Always use `primary` (#000f27) for the deepest tones to maintain the "Navy" brand soul.
*   **DON'T** use "Standard" shadows. If a junior designer applies a default `0 2 4` shadow, it must be flagged in review.
*   **DON'T** use "Success Green" for anything other than financial performance. We are not a "social" app; color is data.