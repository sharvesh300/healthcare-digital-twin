# Twin UI

The dashboard for the healthcare digital twin. It shows a live view of each patient's twin: an
animated figure driven by the twin state, glucose with its band and trend, vital-sign cards,
charts, a change feed, the recorded history and the record. It is built with Next.js 16
(App Router), React 19, Tailwind CSS 4, `motion` and `lucide-react`. The design is in
[../docs/plans/twin-dashboard-ui.md](../docs/plans/twin-dashboard-ui.md).

## Run it

You need the twin API, the UI, and optionally the device simulator. Run each in its own
terminal, from the repository root:

```bash
uv run twin serve                      # API on http://127.0.0.1:8765 (one worker)
bun --cwd twin-ui run dev              # UI on http://localhost:3000
scripts/stream.sh --from-now           # simulated devices stream into the live twin
```

Copy `.env.local.example` to `.env.local` if the API is not on the default address:

| Variable | Used by | Default |
|---|---|---|
| `TWIN_API_URL` | the Next server and the `/api/twin/*` rewrite | `http://127.0.0.1:8765` |
| `NEXT_PUBLIC_TWIN_WS_URL` | the browser's live WebSocket | `ws://127.0.0.1:8765` |
| `NEXT_PUBLIC_TWIN_TZ` | displayed times | `America/Chicago` |

The API accepts WebSocket connections only from the origins in `ALLOWED_ORIGINS`
(default `http://localhost:3000,http://127.0.0.1:3000`).

## Scripts

| Script | What it does |
|---|---|
| `bun run dev` | development server |
| `bun run build` / `bun run start` | production build and server |
| `bun run lint` | ESLint |
| `bun run typecheck` | route types, then `tsc` |
| `bun test` | unit tests (the live store: deltas, version gaps, series) |

## How it fits together

- **Server components** fetch the first state (`lib/api/server.ts`), so a page is complete before
  any socket opens. Every API call is request-time (`connection()`), because the twin is live data.
- **The live page** (`components/live/live-twin.tsx`) opens
  `WS /ws/patients/{id}/state` through `useTwinStream` (`lib/twin/use-twin-stream.ts`).
  - A small external store (`lib/twin/store.ts`) applies each delta in version order.
  - On a gap it asks for a resync.
  - It reconnects with jittered backoff, and a watchdog catches a silent socket.
- **The figure** (`components/twin/twin-figure.tsx`) is SVG with CSS keyframes. Each loop's
  duration comes from a custom property set from the state:
  - `--beat` is 60 / heart rate.
  - `--breath` is 60 / respiration rate.
  - `--stride` follows the activity level.
  - `--aura` is the glucose band colour.

  `motion` handles the one-off transitions: posture, the sleep scene, and the ripples when a band
  changes. `prefers-reduced-motion` stops every loop.
- **Design tokens** live in `app/globals.css` and are mapped to Tailwind utilities. There is one
  light theme, with a sage-tinted neutral background and a teal-green brand colour. Four vital-sign
  hues and the glucose band colours were checked for colour-blind separation. `lib/tokens.ts`
  gives SVG and chart code the same tokens by role name.
