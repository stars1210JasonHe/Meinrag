import { createBrowserRouter } from 'react-router-dom'
import AppLayout from './layouts/AppLayout'
import DashboardPage from './pages/DashboardPage'
import ChatPage from './pages/ChatPage'
import GraphPage from './pages/GraphPage'
import PdfViewerPage from './pages/PdfViewerPage'
import MindmapPage from './pages/MindmapPage'

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
      { path: '/mindmap/:docId', element: <MindmapPage /> },
    ],
  },
])
