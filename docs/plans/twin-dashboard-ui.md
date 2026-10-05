# Plan: twin dashboard UI (`twin-ui/`, Next.js)

Status: implemented (phases 0–4) 2026-10-04, see "As built" at the end · revision 2 · scope: a clean, light-themed live dashboard for one
patient's digital twin. It shows an animated human figure driven by the twin state, sensor
readings, a glucose hero, charts and a change feed. It is built on the live-twin API and leaves
room for the prediction modules.

Revision 2 changes:

- The theme is **light only**.
- The palette is re-done with **no blue**: a sage-tinted neutral canvas and a deep teal-green
  brand colour.
- "In range" glucose is **green** again, made colour-blind-safe through lightness.
- Vitals use **four hues**; sleep uses neutral "night" ink.
- Charts shade only the **target range**, lightly, with hairline thresholds instead of full band
  fills.
- Predictions have no extra colour.
- The open questions are decided (section 11).

## 1. Goal and principles

The dashboard is the face of the project. It should feel like a calm, modern clinical monitor and
show at a glance **how this person is doing right now**, why we think so, and what changed.

1. **One glance, one story.** Glucose is the hero. The figure shows the whole body state. The
   cards give the exact numbers. The feed says what changed.
2. **Quiet surfaces, meaningful colour.** Most of the screen is white and sage-grey. Strong
   colour appears only where it carries meaning: a vital's identity, a glucose band, a problem.
3. **Never colour alone.** Every status has a label and an icon as well as its colour. Every
   palette here was validated with the dataviz checker (OKLab ΔE under colour-blindness
   simulation, contrast against the surface).
4. **Honest data.** Every value shows how old it is and where it came from (live device, fused
   CGM, synthetic generator). Stale data looks stale. Model output never looks like a
   measurement.
5. **Motion with meaning.** The heart beats at the measured heart rate and the chest rises at the
   measured breathing rate. Nothing loops for decoration, and `prefers-reduced-motion` turns every
   loop off.

## 2. What exists

**Frontend.** `twin-ui/` is a fresh `create-next-app`:

- Next.js **16.3** (App Router, Turbopack), React **19.2**, Tailwind CSS **4**, TypeScript, bun.
- Geist fonts are already wired in.
- `AGENTS.md`: this Next.js differs from older versions, and the bundled docs in
  `node_modules/next/dist/docs/` are the reference. The parts that matter here:
  - `params` is a `Promise`.
  - Route handlers cannot hold WebSockets.
  - `rewrites` proxy URLs.

**Backend.** The API from `twin serve` (default `http://127.0.0.1:8765`):

| Route | Use in the UI |
|---|---|
| `GET /patients?tag=` | patient list (identity, tags, sensor window) |
| `GET /patients/{id}` | identity + current twin state (first paint) |
| `WS /ws/patients/{id}/state` | `snapshot` → `delta`s (`version`, `changes` as flat paths, `transitions`) → `heartbeat`; client may send `{"type":"resync"}` |
| `GET /patients/{id}/transitions` | change feed history |
| `GET /twin/{id}` | full record: baseline labs, conditions, medications, CGM metrics, provenance |
| `GET /twin/{id}/timeline` | 5-min recorded series |
| `POST /twin/{id}/simulate/glucose`, `/simulate/hba1c` | **later**: prediction / what-if modules |

The state fields are `glucose` (value, band, trend, rate), `heart_rate`, `activity` (level),
`steps_today`, `sleep` (stage, until), `spo2`, `respiration_rate`, `hrv_rmssd`, `skin_temp`,
`stress`, `eda` and `active_kcal`, plus `streaming`, `version` and `as_of`.

## 3. Architecture

```
Browser
  /patients/[id]  →  <LiveTwin initial={state}>  (client island)
       │  WebSocket  ws://…/ws/patients/{id}/state   — direct to FastAPI
       │  REST       /api/twin/*                      — Next rewrite → FastAPI (no CORS)
       ▼
  TwinStore (useSyncExternalStore): snapshot → apply delta → version check → resync / reconnect
                                    ring buffers (3 h) feed sparklines and live chart tails
Next.js server
  app/patients/[id]/page.tsx  fetches TWIN_API_URL/patients/{id} (no-store) for first paint
  next.config.ts              rewrites /api/twin/:path* → TWIN_API_URL/:path*
FastAPI (twin serve, one worker)
```

- **First paint is server-rendered**, so the page is meaningful before the socket connects.
- **One small external store per patient.** Updates are flat paths from the server, so no
  state library is needed.
- **Types.**
  - REST types are generated from FastAPI's OpenAPI (`openapi-typescript`, `bun run gen:api`).
  - WebSocket message types are written by hand in `lib/api/live.ts` and mirror
    `twin.streaming`.

**Store behaviour (`lib/twin/store.ts`, `use-twin-stream.ts`)**

| Event | Action |
|---|---|
| `snapshot` | replace state, set `version` |
| `delta`, `version === last + 1` | apply `changes` immutably; push glucose and HR points to the ring buffers; prepend `transitions` to the feed |
| `delta` with a gap | send `resync`, ignore deltas until the next snapshot |
| `heartbeat` | refresh the watchdog; version mismatch → `resync` |
| silent 45 s | reconnect |
| socket closed | reconnect with jittered backoff 0.5 → 8 s |
| close 4404 | not-found state, no reconnect |

The connection status is `connecting | live | reconnecting | offline`. It is shown in the top
bar and is separate from the twin's own `streaming` flag, which means devices are sending.

## 4. Design system: light clinical

### 4.1 Direction

**"Sage and ink."** A soft off-white canvas with a hint of green, crisp white cards with a
hairline border, deep teal-green as the single brand colour, and near-black green-tinted ink for
text. It feels like a modern clinic: clean, warm and calm, not sterile blue. Numbers are large
and tabular. There is **one theme (light)**. The tokens are role-named, so a dark theme could be
added later without touching components, but it is out of scope.

### 4.2 Colour tokens

**Neutrals and brand.** The contrast figures are WCAG ratios on white and on the canvas.

| Token | Value | Use | Contrast |
|---|---|---|---|
| `--bg` | `#F6F8F7` | app canvas | |
| `--surface` | `#FFFFFF` | cards, chart surface | |
| `--surface-2` | `#EEF3F1` | sidebar, insets, figure stage, table stripes | |
| `--border` | `#E2E8E5` | card borders, dividers (1 px) | |
| `--border-strong` | `#CBD5D1` | inputs, emphasised dividers | |
| `--text` | `#10231E` | primary ink, hero numbers | 16.4 / 15.4 |
| `--text-2` | `#4B5D57` | labels, secondary text | 7.0 / 6.6 |
| `--text-3` | `#66756F` | captions, timestamps, units | 4.8 / 4.5 (AA) |
| `--primary` | `#0E7C66` | brand, links, focus ring, live dot, primary button | 5.1 / 4.8 |
| `--primary-strong` | `#0B6B58` | hover/pressed | 6.5 |
| `--primary-soft` | `#E3F2EE` | selected row, active nav, soft fills | |

**Vital identities.** There are four hues. Each vital keeps its hue on the figure, its card icon,
its sparkline and its chart line. They were validated across **all pairs**: every check passes.
Rose ↔ teal is ΔE 8.6 under deuteranopia, above the 8 target.

| Vital | Colour | Shown on |
|---|---|---|
| Glucose | `#0D9488` teal | CGM marker, glucose line, sparkline |
| Heart rate, HRV | `#E0335A` rose | heart glyph, HR card and line |
| Oxygen, respiration | `#7C3AED` violet | lungs, SpO₂ and respiration cards |
| Activity, steps, kcal | `#D97706` amber | watch marker, activity and steps cards |
| Sleep | `--text-2` ink + moon icon | sleep card, hypnogram (stages as ink steps), sleep scene |
| Stress, EDA, skin temp | `--text-2` ink + icon | compact "more signals" row |

**Glucose bands** follow the consensus ranges the backend uses.

- **In range is green.** Red and green stay colour-blind-safe by **lightness**: the lows are
  light coral against a deep green, and every adjacent pair passes the colour-blind check.
- **Contrast.** The coral and amber steps fall below 3:1 against white. That is allowed because
  every chip carries its text and icon, and the time-in-range bar is direct-labelled.

| Band | mg/dL | Colour | Icon |
|---|---|---|---|
| `very_low` | < 54 | `#A11A2B` | double chevron down |
| `low` | 54–69 | `#F47C7C` | chevron down |
| `in_range` | 70–180 | `#15803D` | circle-check |
| `high` | 181–250 | `#C99000` | chevron up |
| `very_high` | > 250 | `#B5440D` | double chevron up |
| `stale` | no reading for 15 min | `--text-3` + diagonal hatch | clock-off |

**Status chips** use a 10 % tint of the band as background, the band colour for the icon, and
`--text` for the label, which is always AA. The tints:

| Band | Tint |
|---|---|
| `very_low` | `#A11A2B1A` |
| `low` | `#F47C7C29` |
| `in_range` | `#15803D1A` |
| `high` | `#C990001F` |
| `very_high` | `#B5440D1A` |

**UI status** is reserved for the system (connection, errors), never for data:

| Token | Value |
|---|---|
| `--status-ok` | `#15803D` |
| `--status-warn` | `#B45309` |
| `--status-danger` | `#B91C1C` |
| `--status-info` | `--text-2` ink (no blue) |

**Model output (later)** has no colour of its own. It uses the vital's hue as a **dashed** line,
a **hatched** uncertainty band, and an outlined "Model estimate" badge in ink with a sparkle
icon.

### 4.3 Type, space, shape, motion

| Group | Tokens |
|---|---|
| Font | Geist Sans everywhere. Numbers use `tabular-nums`. Geist Mono only for ids and the device clock |
| Type scale | `display` 56/60 600 (glucose) · `metric` 30/36 600 (card values) · `h1` 22/28 600 · `h2` 16/24 600 · `body` 14/20 · `label` 12/16 500, uppercase, +0.04em (card titles) · `caption` 12/16 |
| Spacing | 4 px base: 4, 8, 12, 16, 20, 24, 32, 48, 64; card padding 20 / 16 (mobile); grid gap 20 / 12 |
| Radius | `sm` 6 (chips) · `md` 10 (buttons, inputs) · `lg` 16 (cards) · `xl` 24 (figure stage) · `full` (dots, pills) |
| Elevation | `shadow-card: 0 1px 2px rgb(16 35 30 / .04), 0 2px 8px rgb(16 35 30 / .04)` and the 1 px border; `shadow-pop` for menus. Hover lifts by 1 px with a slightly stronger shadow |
| Motion | `fast` 150 ms · `base` 250 ms · `slow` 600 ms · `ease-standard: cubic-bezier(.2,.8,.2,1)` · `ease-emphasized: cubic-bezier(.3,0,0,1)` |
| Focus | 2 px `--primary` ring, 2 px offset, on every interactive element |

### 4.4 Where the tokens live

- **`app/globals.css`** is the single source.
  - Raw values go on `:root`.
  - Tailwind 4's `@theme inline` maps them to utilities: `bg-canvas`, `bg-surface`,
    `text-ink-2`, `border-line`, `text-vital-heart`, `bg-band-high/10`, `rounded-card`,
    `shadow-card`, `ease-standard`.
  - The keyframes live here too: `beat`, `breathe`, `sway`, `walk-arm`, `walk-leg`, `ripple`,
    `float-z` and `scan`.
- **`lib/tokens.ts`** exports role names (`vital.glucose`, `band.in_range`, …) as
  `var(--…)` strings for SVG and chart code, so components never use raw hex.
- `<html class="light" style="color-scheme: light">`. No theme toggle and no
  `prefers-color-scheme` branch.

## 5. Layout

### 5.1 Routes

| Route | Page | Phase |
|---|---|---|
| `/` | redirects to `/patients` | 1 |
| `/patients` | cohort overview | 1 |
| `/patients/[id]` | **Live twin** | 2–4 |
| `/patients/[id]/history` | recorded timeline and daily CGM, activity and sleep | 4 |
| `/patients/[id]/record` | labs, conditions, medications, provenance | 4 |
| `/patients/[id]/predict` | forecasts and what-ifs | 5 (later) |

`app/patients/[id]/layout.tsx` holds the patient header and tabs: **Live · History · Record ·
Predict**. Predict shows a muted "soon" pill until phase 5.

### 5.2 Live twin, desktop (≥ 1280 px, 12-column content grid)

```
┌ Sidebar 248 (surface-2) ┬ Top bar (white, hairline bottom) ────────────────────────────────────┐
│ ◆ Twin                  │ Kristeen Gleichner  F · 54 · CGMacros 003   composite  synthetic-sensors │
│ ⌕ Search patients  ⌘K   │                                ● Live · 11:42:07 CDT        ⋯        │
│                         ├ Live · History · Record · Predict(soon) ──────────────────────────────┤
│ PATIENTS                │ ┌ Figure stage (5 cols, surface-2, r24) ┐ ┌ Glucose (7 cols) ──────────┐ │
│ ● K. Gleichner          │ │                                        │ │ GLUCOSE · live CGM · 12 s  │ │
│   186 ↗ High            │ │         animated human figure          │ │ 186 mg/dL  ↗ +2.4/min      │ │
│ ○ J. Doe                │ │   callouts: HR · SpO₂ · CGM · steps    │ │ [▲ High]   ▁▂▃▅▆█ 3 h      │ │
│   112 → In range        │ │   caption: Walking · moderate          │ │ Today ▇▇█████▇▆  72% in range│ │
│ …                       │ │                                        │ ├ Vitals 3 × 2 ──────────────┤ │
│                         │ │                                        │ │ Heart │ SpO₂  │ Breathing  │ │
│ ─────────               │ └────────────────────────────────────────┘ │ Activity│ Steps│ Sleep     │ │
│ ◉ Live                  │ ┌ Glucose · 6 h (8 cols) ─────────────────┐ ┌ What changed (4 cols) ────┐ │
│ ○ History               │ │ faint green target band, 70/180 hairlines│ │ 11:41 Glucose In range→High│ │
│ ○ Record                │ │ teal line, live tail, crosshair          │ │ 11:30 Activity Light→Mod.  │ │
│ ○ Predict  soon         │ ├ Heart rate · 6 h (8 cols) ───────────────┤ │ 11:12 Heart rate → stale   │ │
│                         │ └──────────────────────────────────────────┘ └────────────────────────────┘ │
│                         │ More signals: HRV 42 ms · Skin 33.1 °C · Stress 24 · EDA 0.41 µS · 312 kcal │
└─────────────────────────┴─────────────────────────────────────────────────────────────────────────┘
```

- **Tablet (768–1279).** The sidebar becomes an icon rail with a patient switcher (⌘K). The
  figure and glucose sit side by side. Vitals are 3 × 2. Charts are full width, and the feed sits
  below them.
- **Mobile (< 768).** One column: header → glucose → compact figure (220 px) → vitals in 2
  columns → glucose chart → feed. The tabs become a segmented control. 16 px gutters and no
  horizontal scroll.

### 5.3 Cohort overview (`/patients`)

- **Row.** A white card table with one row per patient:
  - name and subject id
  - cohort chip
  - tags
  - sensor window
  - live dot
  - latest glucose, as value + band chip + trend arrow
  - an "Open twin" link
- **Controls.** A search box, a tag filter and a "streaming only" toggle sit in one row above
  the table.
- **Empty state.** "Start streaming a patient" with the `scripts/stream.sh` command.

### 5.4 Components

| Component | Contents |
|---|---|
| `GlucoseHero` | `display` value + unit; band chip; trend arrow (5 arrows from `trend`) + rate; source and age; 3 h sparkline (teal line, faint target band); today's time-in-range bar (5 direct-labelled segments with 2 px white gaps) |
| `VitalCard` | uppercase label + icon in the vital hue; `metric` value + unit; status chip if the signal has one; age; mini sparkline; **stale** = hatched background, value in `--text-3`, "no data for 14 min" |
| `TwinFigure` | section 6 |
| `TransitionFeed` | newest first; signal icon, `from → to` chips, value, device time; new items slide in (250 ms); "load older" uses `/transitions?since=` |
| `TimeSeriesChart` | one measure per chart (no dual axis); 2 px line in the vital hue; glucose: a **6 % green target band (70–180) plus hairline dashed thresholds at 54, 70, 180 and 250**, never full-height colour fills; live tail; crosshair + tooltip; 3 h · 6 h · 24 h range control above; table-view toggle |
| `ConnectionBadge` | `● Live` (teal pulsing dot) · `Reconnecting…` (amber) · `Offline` (ink) · `Not streaming · last data 3 h ago` |
| `ProvenanceTag` | `Live device` · `Fused CGM` · `Synthetic` (hatched chip) |

Primitives come from **shadcn/ui** (Radix-based; works with Tailwind 4; the code is copied into
`components/ui`):

- Button, Card, Badge, Tabs, Tooltip
- DropdownMenu, Command (⌘K patient search), ScrollArea, Skeleton, Sheet (mobile nav)

Icons come from **lucide-react**.

### 5.5 States

| State | Treatment |
|---|---|
| Loading | Skeletons in the card and chart shapes; figure silhouette at 30 % opacity |
| Not streaming | Last-known values with their age; the figure is desaturated and still; a soft banner shows `scripts/stream.sh --patient <id>` |
| Signal stale | Hatched card, muted value, "stale" chip; the matching body part greys out |
| Reconnecting | Top-bar badge only; data stays, with no layout shift |
| Unknown patient | `not-found.tsx` with a link to the cohort |
| Error | `error.tsx` with retry |

## 6. The human figure (`components/twin/figure/`)

**Choice: an in-house, layered SVG figure.**

- **Tools.** It is animated with CSS custom properties, and `motion` (`motion/react`) handles the
  discrete transitions.
- **Why SVG.** It is crisp, uses the same tokens, is accessible, weighs under 20 KB, and has no
  asset licensing. Every region is its own group, driven by one state field.
- **Later.** A 3D upgrade (React Three Fiber with a rigged glTF) remains possible behind the same
  props.

**Look, on the light stage:**

- **Stage.** `--surface-2` with radius 24, a 1 px `--border`, a faint 8 px dot grid in
  `--border`, and a slow vertical scan line (white, 40 % opacity, every 6 s; reduced motion: off).
- **Body.** A stylised, gender-neutral front view. The fill is white, the outline 1.5 px
  `--border-strong`, with soft inner shading in `--surface-2`. It reads as a "digital twin" model,
  not a medical illustration.
- **Organs.** Simple glyphs in their vital hue: the heart in rose, the lungs in violet at 25 %
  fill. A metabolic "aura" sits behind the torso in the glucose band colour.
- **Devices.** The **CGM** puck on the back of the left upper arm (teal ring) and a **watch** on
  the left wrist (amber).
- **Callouts.** Hairline leader lines to small labels (`HR 92`, `SpO₂ 97 %`, `186 ↗`,
  `4,210 steps`). Hovering a callout highlights its card, and the reverse.

**State → animation**

| Twin state | Figure behaviour |
|---|---|
| `heart_rate.value` | "lub-dub" pulse (scale 1 → 1.12 → 1.04 → 1) + a ripple ring; period = 60 / HR s (`--beat`). Stale → grey, still |
| `heart_rate.status` | `elevated`: a stronger ripple; `low`: a slower, fainter ripple |
| `respiration_rate.value` | chest and lungs scale 1 → 1.025 on the Y axis, period = 60 / RR s (`--breath`); default 15/min |
| `spo2.status` | lung fill: `normal` 25 % violet, `borderline` 15 %, `low` 10 % with an amber outline |
| `glucose.status` | aura: a radial glow in the band colour at 18 % opacity, cross-fading over 600 ms; `very_low` / `very_high` add a slow 2 s glow |
| `glucose.trend` | a small arrow beside the CGM puck; a band transition sends one ripple from the puck (1.2 s, once) |
| `activity.status` | posture: `sedentary` still; `light` a weight-shift sway (4 s); `moderate` a walk cycle (1.2 s); `vigorous` a brisk walk (0.8 s). Limbs rotate about shoulder and hip pivots |
| `sleep.status` light/deep/rem | **sleep scene**: the stage tint eases to a soft dusk grey (`#E7ECEA`), the figure reclines onto a bed line (800 ms), the eyes close and small "z"s float up (fewer in deep sleep), with a stage label in ink; `awake` reverses it |
| `stress` / `eda` | subtle head halo intensity in ink (no hue) |
| `streaming = false` | figure at 60 % saturation, loops paused, "last seen 3 h ago" caption |

**Implementation**

- **Loops are CSS keyframes** whose durations come from custom properties set by React
  (`--beat: ${60/hr}s`). They run off the main thread, and React re-renders only when a delta
  changes an input.
- **`motion` handles one-off transitions:** posture, the sleep scene, the aura cross-fade and
  number tweens.
- **Reduced motion:** no loops. The state is shown statically: the pose, the aura colour, and a
  "♥ 92" badge instead of a pulse.
- **Accessibility.** The figure is `role="img"` with a live summary ("Heart rate 92, normal.
  Glucose 186, high, rising. Walking."). An `aria-live="polite"` region announces band
  transitions, at most one every 10 s.

## 7. Backend work (small, in `src/twin/api`)

1. **`GET /patients/{id}/readings?metrics=glucose,heart_rate&since=&until=`** returns points for
   the charts and sparklines, including live-device data. `/twin/{id}/timeline` excludes live
   data, so it can't seed charts after a reload.
2. **Pydantic response models** for `/patients/{id}`, `/transitions` and the WS messages, so
   OpenAPI types the client.
3. **`GET /patients`** gains `streaming` and the cached glucose value and band for loaded
   patients, for the live dots and glucose column without one socket per patient.
4. **`TWIN_ALLOWED_ORIGINS`** setting (default `http://localhost:3000`), checked against the
   WebSocket `Origin`.
5. **Later:** a `forecast` WS message after each glucose delta, and `GET /patients/{id}/forecast`.

## 8. Frontend structure

```
twin-ui/
  app/
    layout.tsx              Geist fonts, <html class="light">, metadata
    globals.css             tokens (§4) + @theme mapping + figure keyframes
    page.tsx                redirect → /patients
    patients/page.tsx       cohort overview (server)
    patients/[id]/
      layout.tsx            patient header + tabs (server)
      page.tsx              <LiveTwin initial={state}/> (client island)
      loading.tsx error.tsx not-found.tsx
      history/ record/ predict/
  components/
    ui/                     shadcn primitives
    shell/                  app-sidebar, top-bar, patient-switcher, connection-badge
    twin/figure/            twin-figure, body, organs, devices, poses, sleep-scene
    vitals/                 glucose-hero, vital-card, band-chip, trend-arrow, tir-bar, sparkline
    charts/                 time-series-chart (visx), target-band, crosshair-tooltip
    feed/                   transition-feed
  lib/
    api/                    client.ts, schema.d.ts (generated), live.ts (WS types)
    twin/                   store.ts, use-twin-stream.ts, apply-delta.ts, format.ts
    tokens.ts
  next.config.ts            rewrites /api/twin/:path*
  .env.local.example        TWIN_API_URL, NEXT_PUBLIC_TWIN_WS_URL
```

**Dependencies to add:**

- `motion`, `lucide-react`
- `@visx/{scale,shape,axis,tooltip,responsive,group}`
- shadcn/ui (`bunx shadcn@latest init`)
- dev: `openapi-typescript`, `vitest`, `@playwright/test`

## 9. Phases

| Phase | Deliverable | Done when |
|---|---|---|
| **0. API prep** | §7 items 1–4, with pytest | OpenAPI is typed; readings return live + recorded points |
| **1. Foundation** | tokens, fonts, shadcn, app shell (sidebar, top bar, tabs), API client + types, rewrites, `/patients` | checked at 1440 / 1024 / 390 px; no layout shift; axe clean |
| **2. Live data** | store + `useTwinStream`, glucose hero, vital cards, connection badge, transition feed | values update on every batch from `scripts/stream.sh --from-now`; stopping the API shows "Reconnecting…" and recovery works without a reload; Vitest covers apply-delta, gap → resync and backoff |
| **3. Human figure** | `TwinFigure`: heartbeat, breathing, aura, postures, sleep scene, callouts, reduced-motion variant | the figure visibly tracks a 60× stream (walk ↔ still, night sleep, aura on band change); 60 fps in Chrome performance; correct and still under reduced motion |
| **4. Charts and history** | glucose and HR charts with the target band and live tail; History and Record tabs | crosshair tooltips, table view, 3/6/24 h; dataviz anti-pattern check passes |
| **5. Predictions (later)** | Predict tab: +30/+60 forecast as a dashed line with a hatched band on the glucose chart; glucose and HbA1c what-if sandbox (`/simulate/*`); model caveat always visible | model output never uses solid measurement styling |

**Quality gates (every phase):**

- `bun run lint`, `tsc`.
- axe: no serious issues; Lighthouse accessibility ≥ 95; text AA.
- A Playwright smoke test against `twin serve` + `simulate-stream`: open a patient, wait for a
  delta, see the glucose value change.

## 10. Design review checklist (before each phase is called done)

- One brand colour, four vital hues, the band colours, ink. Nothing else.
- Every number in a `--text*` ink. Colour only on marks, icons and chips.
- Every status: icon + label + colour.
- Charts: one measure per chart, 2 px lines, recessive axes and grid, faint target band only.
- Ages on every value; stale values look stale.
- Card rhythm: 20 px padding, 20 px gaps, radius 16, 1 px borders; no nested cards.
- Motion: only physiological loops; all off with reduced motion.

## 11. Decisions (were open questions)

- **Theme:** light only. The tokens are role-named, so a dark theme could be added later without
  touching components.
- **Patient display:** the Synthea name plus the subject id. An "anonymise" toggle for demos
  shows only `CGMacros 003` (phase 1, client-side).
- **Figure:** SVG now. 3D is optional after phase 5.

## 12. As built

Phases 0–4 are implemented. Predict (phase 5) is a placeholder tab. Differences from the plan:

- **No shadcn/ui, visx or openapi-typescript.** The primitives (card, chips, segmented control,
  switch, drawer) and the charts are small in-house components on the tokens. This keeps the
  dependency list short: `motion`, `lucide-react` and `clsx`. The REST and WebSocket types are
  written by hand in `lib/api/types.ts`.
- **Unit tests use `bun test`** (`lib/twin/store.test.ts`) instead of Vitest. Playwright is not
  set up yet. The pages were checked in the browser against a live 30× stream at
  1440 × 1000 and 375 × 812 px:
  - the walk cycle, heartbeat and breathing run at the measured rates;
  - the sleep scene;
  - band transitions in the feed;
  - reconnecting after an API restart.
- **No steps, so active energy instead.** Patients whose wearable records no steps (the
  CGMacros Fitbits) see an "Active energy" card and figure callout in their place.
- **Backend changes:**
  - `GET /patients/{id}/readings`.
  - The `live` summary in `GET /patients`.
  - The WebSocket `Origin` check against `ALLOWED_ORIGINS`.
  - `/twin/{id}/timeline` now returns numbers, not decimal strings.
- **Every API call runs at request time** (`connection()` in `lib/api/server.ts`), so a build
  never needs the API.

### Replay (added 2026-10-04)

The Live tab has a **Live now / Replay** switch. Replay reuses the whole live view: the figure,
glucose card, vital cards, charts and feed. Only the clock and the data source change.

- **Server.** `twin/streaming/replay.py`, the `ReplayEngine`, is pure.
  - It folds the recorded readings (`SqlStateLoader.recorded`: fused CGM, recorded wearables,
    sleep stages) through `apply_readings`, the same rules as the live twin.
  - It starts with 24 h of warm-up, so the state at the window's start is complete.
  - It emits the live protocol: a `snapshot`, then deltas with sequential versions, then
    transitions.
  - `WS /ws/patients/{id}/state/replay?start=&end=&speed=&autoplay=` runs it on a 250 ms tick.
    It takes `play`, `pause`, `seek` and `speed` commands and sends `replay` progress messages.
- **Snapshots now carry context.** Live and replay snapshots include `series` (24 h of glucose
  and heart-rate points) and `feed` (recent transitions). Any snapshot can therefore rebuild the
  view: a reconnect, a switch between live and replay, or a seek.
- **Client.**
  - `useTwinStream(patientId, init, source)` takes a live or replay source. Changing the source
    swaps in a fresh store that starts from what is on screen.
  - A replay doesn't reconnect.
  - Ages are measured on the replay clock.
  - `ReplayBar` has window presets, From / To pickers in the clinic zone, play / pause, a
    scrubber and a speed control.
- **Checked in the browser:**
  - preview at the window start;
  - play at 120× (7.5 device-minutes per 4 s);
  - a scrub-seek;
  - switching to 600×;
  - the "Last night" preset showing the sleep scene at 01:00;
  - "Live now" returning to the live twin;
  - the 375 px layout.

### Moment inspection and the full-signal figure (added 2026-10-05)

- **Figure.** HRV joins the heart callout; stress gets a halo around the head (hidden at rest and
  while asleep); a wristband on the other arm carries skin temperature and EDA callouts, with
  sparks timed by EDA; METs join the posture caption. Out-of-range callouts (heart rate, SpO₂,
  glucose, high stress) get a ring in the band or warning colour, and every callout's tooltip
  gives its status and age.
- **Charts.** `SeriesSpec.flag` shades out-of-range runs (glucose bands; heart rate below 50 or
  above 100). `ChartCard`'s `inspect` pins a clicked point in a popover: the value, the other
  vital then, nearby transitions, and an action. The table view gets an Inspect button per row.
- **Feed.** Events are buttons; an **All / Alerts** filter keeps the out-of-range ones
  (`isAbnormal` in `lib/twin/format.ts`).
- **Opening a moment.** `LiveTwin.inspect(t)` seeks if the open replay covers `t`, else opens a
  replay from an hour before to two hours after, paused at `t` (`at=`). A banner names the
  moment and offers "Back to {time}" and "Back to live"; the scrubber marks it; `?at=` keeps it
  in the URL (History links there).
- **Server.** The replay socket takes `at` (open there instead of at `start`) and `live`
  (`SqlStateLoader.recorded(..., live=True)` adds the simulator's readings, each recording cut
  at its first streamed reading, as the chart series are). The dashboard always asks for
  `live=true`, and the replayable extent runs from the recording's start to the newest reading
  seen live, since streamed moments lie past the recording.

