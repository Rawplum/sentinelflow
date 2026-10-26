# SentinelFlow Frontend

React + TypeScript security operations console for the SentinelFlow backend.

## Status

- Login and JWT session handling: implemented and tested.
- Dashboard, events, alerts, report, and audit pages: implemented and tested.
- Admin import and detection actions: implemented and tested.
- Analyst read-only enforcement: backend returns 403; UI hides admin controls.
- Backend API unchanged.

Current environment used for verification:

- Node.js 24.20.0 (portable distribution)
- npm 11.19.0
- React 19.3.1
- Vite 8.3.5
- React Router 7.18.4
- Axios 1.20.0
- TanStack Query 5.104.5
- Vitest 5.0.5 + React Testing Library + MSW 3

Node.js 20.19+ or 22.12+ is recommended for Vite 8. Use an LTS release.

## Prerequisites

1. Backend running at `http://127.0.0.1:8000` with PostgreSQL.
2. Database migrated and at least one local user created:

```bat
alembic upgrade head
sentinelflow-create-user --username admin --role admin
sentinelflow-create-user --username analyst1 --role analyst
```

3. Backend `.env` contains a valid `JWT_SECRET`.

## Setup

```bat
cd /d G:\软件开发\frontend
npm install
copy .env.example .env
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173).

`vite.config.ts` proxies `/api` and `/health` to `http://127.0.0.1:8000`, so the backend does not need CORS configuration for local development.

Environment variables:

```dotenv
VITE_API_BASE_URL=/api/v1
VITE_PROXY_TARGET=http://127.0.0.1:8000
```

`VITE_API_BASE_URL` is a public client-side base URL, not a secret. Never put JWT secrets in frontend environment variables.

## Pages and permissions

| Route | Page | admin | analyst |
| --- | --- | --- | --- |
| `/login` | 登录 | public | public |
| `/dashboard` | 仪表盘 | yes | yes |
| `/events` | 安全事件 | yes | read-only |
| `/alerts` | 告警 | yes | read-only |
| `/alerts/:alertId/report` | 调查报告 | yes | yes |
| `/audit` | 操作审计 | yes | 403 |

Admin-only controls:

- 导入合成安全事件（JSON / JSONL，1–500 条）。
- 运行 AUTH-001 检测。
- 查看操作审计。

Analyst sees a read-only dashboard and no audit navigation. Permissions are still enforced by the backend; hiding a button is not the security boundary.

## Usage

1. Login with a CLI-created account.
2. Dashboard shows total events, total alerts, recent alerts/events, severity distribution from the latest loaded sample, and admin operations.
3. Events page supports pagination, opening a detail drawer, and admin import.
4. Alerts page supports pagination, opening reports, and admin detection.
5. Report page renders summary, risk, evidence, timeline, reasoning, recommended actions, and limitations from the backend.
6. Audit page supports pagination and exact `action` filtering for admins.

The dashboard does not invent global statistics. Severity distribution is based on the latest 100 alerts and is labeled as a sample when the total is larger.

## Commands

```bat
npm run dev        # Vite dev server with backend proxy
npm run typecheck  # TypeScript project build check
npm run lint       # oxlint
npm test           # Vitest run
npm run build      # production build
npm run preview    # preview built assets
```

Actual verification in this environment:

```text
npm run typecheck  -> passed
npm run lint       -> 0 warnings, 0 errors
npm test           -> 8 files, 24 tests passed
npm run build      -> passed
```

## Manual verification performed

- Admin login with real backend and PostgreSQL.
- Dashboard loaded 24 events, then detection created 2 alerts.
- Report page loaded 5 evidence events and matched backend report IDs.
- Admin import modal imported one synthetic event; events total changed 24 → 25.
- Alert severity distribution and recent alerts rendered.
- Audit page loaded 10 records and filtered by `auth.login`.
- Events pagination changed to 20/page and moved to page 2 (21–25 of 25).
- Analyst login:
  - no audit navigation;
  - no detection/import controls;
  - direct `/audit` showed the 403 page;
  - browser `fetch` checks returned `audit: 403`, `detection: 403`, `events: 200`.
- Clearing sessionStorage and reloading `/events` redirected to `/login`.
- No console errors were captured during SPA navigation.
- Vite proxy log showed no request errors.

## Security notes

- The access token is stored in `sessionStorage` for this demo. It is cleared when the tab closes and on logout/401. This is not a production best practice: sessionStorage is still accessible to injected JavaScript. Production should use HttpOnly cookies, short-lived tokens, CSP, CSRF protections where applicable, and token revocation.
- No JWT, password, or API key is hardcoded in source.
- Raw event messages are rendered as text, never injected as HTML.
- The UI only uses fields present in the backend OpenAPI response.
- Backend authorization is authoritative; route guards only improve UX.

## Known backend gaps surfaced by the UI

- No alert detail endpoint; the report page shows report fields. Alert titles/status are passed via router state when navigating from the list.
- No alert status update or report finalize/persistence endpoints, so no such buttons are shown.
- No event/alert filtering beyond pagination; no search UI is faked.
- No dashboard statistics endpoint; totals come from paginated responses and severity distribution is sample-based.
- The report `limitations` text still contains one stale backend sentence saying authentication/access control are not implemented. The frontend displays backend content as-is; this should be corrected in the backend in a separate change.
- `/docs` and `/openapi.json` remain public in the backend; restrict them for production.

## Structure

```text
src/
├── api/          # typed Axios client, errors, endpoint modules
├── auth/         # session storage, AuthContext, route guards
├── components/   # layout, UI, domain components
├── pages/        # login, dashboard, events, alerts, report, audit
├── hooks/        # pagination hook
├── lib/          # formatting, constants, event parser
├── styles/       # design tokens and global styles
└── __tests__/    # Vitest + RTL + MSW tests
```
