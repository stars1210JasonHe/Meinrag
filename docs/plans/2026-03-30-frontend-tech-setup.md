# Frontend Tech Setup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate frontend from hand-written CSS + axios to Tailwind CSS + shadcn/ui + react-query + react-router, with a 4-page routing skeleton ready for page implementations.

**Architecture:** Install new dependencies, configure Tailwind + shadcn, set up react-router with 4 routes, create shared layout (sidebar + topbar), replace axios with react-query + fetch. Keep old components working during migration — don't delete anything yet.

**Tech Stack:** React 19, Vite 7, Tailwind CSS, shadcn/ui, @tanstack/react-query, react-router-dom, vis-network

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/package.json` | Modify | Add new dependencies |
| `frontend/tailwind.config.js` | Create | Tailwind configuration with dark theme |
| `frontend/postcss.config.js` | Create | PostCSS for Tailwind |
| `frontend/src/index.css` | Create | Tailwind base imports |
| `frontend/components.json` | Create | shadcn/ui config |
| `frontend/src/lib/utils.js` | Create | shadcn utility (cn function) |
| `frontend/src/lib/api.js` | Create | React-query + fetch API layer |
| `frontend/src/App.jsx` | Modify | Add QueryClientProvider + RouterProvider |
| `frontend/src/router.jsx` | Create | Route definitions |
| `frontend/src/layouts/AppLayout.jsx` | Create | Shared sidebar + content area |
| `frontend/src/pages/DashboardPage.jsx` | Create | Placeholder page |
| `frontend/src/pages/ChatPage.jsx` | Create | Placeholder page |
| `frontend/src/pages/GraphPage.jsx` | Create | Placeholder page |
| `frontend/src/pages/PdfViewerPage.jsx` | Create | Placeholder page |

---

## Task 1: Install Dependencies

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install Tailwind CSS + PostCSS**

```bash
cd frontend
npm install -D tailwindcss @tailwindcss/vite
```

- [ ] **Step 2: Install shadcn/ui prerequisites**

```bash
npm install tailwind-merge clsx class-variance-authority
npm install -D @types/node
```

- [ ] **Step 3: Install react-router + react-query + vis-network**

```bash
npm install react-router-dom @tanstack/react-query vis-network vis-data
```

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "deps: add tailwind, shadcn, react-query, react-router, vis-network"
```

---

## Task 2: Configure Tailwind + Dark Theme

**Files:**
- Modify: `frontend/vite.config.js`
- Create: `frontend/src/index.css`

- [ ] **Step 1: Update vite.config.js**

Read `frontend/vite.config.js` first. Add the Tailwind plugin:

```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
```

- [ ] **Step 2: Create src/index.css**

```css
@import "tailwindcss";

/* Dark theme base */
:root {
  --background: 222 47% 6%;
  --foreground: 210 40% 98%;
  --card: 222 47% 8%;
  --card-foreground: 210 40% 98%;
  --primary: 250 80% 65%;
  --primary-foreground: 210 40% 98%;
  --secondary: 217 33% 17%;
  --secondary-foreground: 210 40% 98%;
  --muted: 217 33% 17%;
  --muted-foreground: 215 20% 65%;
  --accent: 168 84% 40%;
  --accent-foreground: 210 40% 98%;
  --destructive: 0 84% 60%;
  --border: 217 33% 17%;
  --input: 217 33% 17%;
  --ring: 250 80% 65%;
  --radius: 0.5rem;
}

body {
  @apply bg-[hsl(var(--background))] text-[hsl(var(--foreground))];
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  margin: 0;
}

/* Keep old App.css working during migration */
```

- [ ] **Step 3: Import index.css in main.jsx**

Read `frontend/src/main.jsx`. Add at the top (before App.css import):

```javascript
import './index.css'
```

- [ ] **Step 4: Commit**

```bash
git add frontend/vite.config.js frontend/src/index.css frontend/src/main.jsx
git commit -m "config: tailwind dark theme + vite integration"
```

---

## Task 3: shadcn/ui Setup

**Files:**
- Create: `frontend/components.json`
- Create: `frontend/src/lib/utils.js`

- [ ] **Step 1: Create components.json**

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "tailwind": {
    "config": "",
    "css": "src/index.css",
    "baseColor": "slate",
    "cssVariables": true
  },
  "aliases": {
    "components": "@/components/ui",
    "utils": "@/lib/utils"
  }
}
```

- [ ] **Step 2: Create lib/utils.js**

```javascript
import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs) {
  return twMerge(clsx(inputs))
}
```

- [ ] **Step 3: Install a few shadcn components to verify setup**

```bash
cd frontend
npx shadcn@latest add button card input tabs
```

If the CLI asks questions, use defaults. This creates files in `frontend/src/components/ui/`.

- [ ] **Step 4: Commit**

```bash
git add frontend/components.json frontend/src/lib/ frontend/src/components/ui/
git commit -m "config: shadcn/ui setup with button, card, input, tabs components"
```

---

## Task 4: React Query + API Layer

**Files:**
- Create: `frontend/src/lib/api.js`

- [ ] **Step 1: Create API layer with react-query**

```javascript
import { QueryClient } from '@tanstack/react-query'

const API_BASE = import.meta.env.VITE_API_URL

if (!API_BASE) {
  console.error('VITE_API_URL is not set. Create frontend/.env with VITE_API_URL=http://localhost:<PORT>')
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
})

function headers(userId) {
  return {
    'X-User-Id': userId || 'admin',
    'Content-Type': 'application/json',
  }
}

async function apiFetch(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, options)
  if (!resp.ok) {
    const err = await resp.text().catch(() => resp.statusText)
    throw new Error(`API ${resp.status}: ${err}`)
  }
  return resp.json()
}

// --- Documents ---
export const fetchDocuments = (userId) =>
  apiFetch('/documents', { headers: headers(userId) })

export const fetchCollections = (userId) =>
  apiFetch('/documents/collections', { headers: headers(userId) })

export const deleteDocument = (docId, userId) =>
  apiFetch(`/documents/${docId}`, { method: 'DELETE', headers: headers(userId) })

export const fetchDocumentChunks = (docId, page, userId) => {
  const params = page != null ? `?page=${page}` : ''
  return apiFetch(`/documents/${docId}/chunks${params}`, { headers: headers(userId) })
}

// --- Graph ---
export const fetchGraphDocuments = (userId) =>
  apiFetch('/graph/documents', { headers: headers(userId) })

export const fetchGraphNodes = (docId, edgeTypes, userId) => {
  const params = `?doc_id=${docId}&edge_types=${edgeTypes || 'follows,co_located,describes,references,similar_to'}`
  return apiFetch(`/graph/nodes${params}`, { headers: headers(userId) })
}

export const fetchGraphNeighbors = (docId, chunkIndex, hops, userId) =>
  apiFetch(`/graph/neighbors?doc_id=${docId}&chunk_index=${chunkIndex}&hops=${hops || 1}`, { headers: headers(userId) })

// --- Query ---
export const sendQuery = (question, options, userId) =>
  apiFetch('/query', {
    method: 'POST',
    headers: headers(userId),
    body: JSON.stringify({ question, ...options }),
  })

// --- Sessions ---
export const fetchSessions = (userId) =>
  apiFetch('/sessions', { headers: headers(userId) })

export const fetchSessionMessages = (sessionId, userId) =>
  apiFetch(`/sessions/${sessionId}/messages`, { headers: headers(userId) })

// --- Users ---
export const fetchUsers = () => apiFetch('/users')

// --- Health ---
export const fetchHealth = () => apiFetch('/health')
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat: react-query API layer replacing axios"
```

---

## Task 5: Router + Page Skeleton

**Files:**
- Create: `frontend/src/router.jsx`
- Create: `frontend/src/layouts/AppLayout.jsx`
- Create: `frontend/src/pages/DashboardPage.jsx`
- Create: `frontend/src/pages/ChatPage.jsx`
- Create: `frontend/src/pages/GraphPage.jsx`
- Create: `frontend/src/pages/PdfViewerPage.jsx`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Create router.jsx**

```jsx
import { createBrowserRouter } from 'react-router-dom'
import AppLayout from './layouts/AppLayout'
import DashboardPage from './pages/DashboardPage'
import ChatPage from './pages/ChatPage'
import GraphPage from './pages/GraphPage'
import PdfViewerPage from './pages/PdfViewerPage'

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { path: '/', element: <DashboardPage /> },
      { path: '/chat', element: <ChatPage /> },
      { path: '/chat/:sessionId', element: <ChatPage /> },
      { path: '/graph', element: <GraphPage /> },
      { path: '/graph/:docId', element: <GraphPage /> },
      { path: '/pdf/:docId', element: <PdfViewerPage /> },
    ],
  },
])
```

- [ ] **Step 2: Create AppLayout.jsx**

```jsx
import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { LayoutDashboard, MessageSquare, Network, FileText, Upload, Settings, HelpCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/chat', icon: MessageSquare, label: 'Chat' },
  { to: '/graph', icon: Network, label: 'Graph' },
]

export default function AppLayout() {
  return (
    <div className="flex h-screen bg-[hsl(var(--background))]">
      {/* Sidebar */}
      <nav className="group flex w-14 hover:w-48 flex-col border-r border-[hsl(var(--border))] bg-[hsl(var(--card))] transition-all duration-200 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-4 border-b border-[hsl(var(--border))]">
          <Network size={20} className="text-[hsl(var(--primary))] shrink-0" />
          <span className="text-sm font-semibold whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
            MeinRAG
          </span>
        </div>

        <div className="flex-1 py-2">
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 px-4 py-2.5 text-sm transition-colors',
                  isActive
                    ? 'text-[hsl(var(--primary))] bg-[hsl(var(--secondary))]'
                    : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--secondary))]'
                )
              }
            >
              <Icon size={18} className="shrink-0" />
              <span className="whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
                {label}
              </span>
            </NavLink>
          ))}
        </div>

        <div className="border-t border-[hsl(var(--border))] py-2">
          <button className="flex items-center gap-3 px-4 py-2.5 text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] w-full">
            <Settings size={18} className="shrink-0" />
            <span className="whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">Settings</span>
          </button>
          <button className="flex items-center gap-3 px-4 py-2.5 text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] w-full">
            <HelpCircle size={18} className="shrink-0" />
            <span className="whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">Help</span>
          </button>
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
```

- [ ] **Step 3: Create placeholder pages**

`frontend/src/pages/DashboardPage.jsx`:
```jsx
export default function DashboardPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-4">Dashboard</h1>
      <p className="text-[hsl(var(--muted-foreground))]">Document search and management — coming soon.</p>
    </div>
  )
}
```

`frontend/src/pages/ChatPage.jsx`:
```jsx
export default function ChatPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-4">AI Chat</h1>
      <p className="text-[hsl(var(--muted-foreground))]">Query your documents — coming soon.</p>
    </div>
  )
}
```

`frontend/src/pages/GraphPage.jsx`:
```jsx
export default function GraphPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-4">Knowledge Graph</h1>
      <p className="text-[hsl(var(--muted-foreground))]">Explore document relationships — coming soon.</p>
    </div>
  )
}
```

`frontend/src/pages/PdfViewerPage.jsx`:
```jsx
export default function PdfViewerPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-4">PDF Viewer</h1>
      <p className="text-[hsl(var(--muted-foreground))]">Read documents — coming soon.</p>
    </div>
  )
}
```

- [ ] **Step 4: Update App.jsx**

Read `frontend/src/App.jsx` first. This is the big change — we need to wrap everything with QueryClientProvider and RouterProvider. For now, the new router lives alongside the old app:

Replace the entire App.jsx content with:

```jsx
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { queryClient } from './lib/api'
import { router } from './router'

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
```

**WARNING:** This completely replaces the old UI. The old components (Header, Sidebar, ChatArea, etc.) are NOT deleted — they're just not rendered anymore. They can be pulled back in as we build the new pages.

- [ ] **Step 5: Run dev server and verify**

```bash
cd frontend && npm run dev
```

Open http://localhost:5173 — should see:
- Dark background
- Left sidebar with Dashboard/Chat/Graph icons
- Sidebar expands on hover showing labels
- Click each nav item → shows placeholder page
- Routes: `/`, `/chat`, `/graph`, `/pdf/:docId`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "feat: react-router + page skeleton with sidebar layout"
```

---

## Summary

| Before | After |
|--------|-------|
| Single-page chat app | 4-page app with routing |
| Hand-written App.css (2100 lines) | Tailwind CSS + CSS variables |
| No UI component library | shadcn/ui components |
| axios | react-query + fetch |
| No graph library | vis-network installed |
| No router | react-router-dom with 4 routes |

**Old code preserved:** All existing components still exist in `src/components/`. App.css still exists. They're just not rendered by the new App.jsx. Can be reused/referenced when building new pages.

**Next plans:** Dashboard Page → Chat Page → Graph Page → PDF Viewer Page (separate plans for each).
