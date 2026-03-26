# GP Advisor Frontend

This frontend is aligned only to the new backend surface:

- `POST /api/chat`
- `GET /api/health`
- `GET /api/book/current`
- `GET /api/session/{session_id}`
- `GET /api/run/{run_id}`
- `GET /api/side-results`

There is no compatibility layer for the old chat/recommend/workbench/search/history pages.

## View model

The UI is built around three truths exposed by the backend:

1. **Session Truth**: `/api/session/{session_id}`
2. **Market Book**: `/api/book/current`
3. **Advice Run**: `/api/run/{run_id}`

The page layout is therefore:

- left: session truth + quick prompts
- center: transcript + composer
- right: board / active run / side results

## Source tree

- `src/features/workspace/useAdvisorWorkspace.ts`: main data orchestration
- `src/features/workspace/WorkspacePage.tsx`: shell layout
- `src/features/workspace/components/*`: pure UI panels
- `src/shared/contracts.ts`: backend contract mirror
- `src/shared/api.ts`: HTTP client

## Rules

- no routing for legacy pages
- no adapter for old panel payloads
- no client-side fallback when LLM is unavailable
- no separate recommendation workbench outside the chat workspace
