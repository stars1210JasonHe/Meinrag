import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { Toaster } from 'sonner'
import { queryClient } from './lib/api'
import { router } from './router'
import { SelectionProvider } from './hooks/useSelection'

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <SelectionProvider userId="admin">
        <RouterProvider router={router} />
        <Toaster
          position="bottom-right"
          theme="system"
          toastOptions={{
            style: {
              background: 'var(--bg-2)',
              border: '1px solid var(--border-strong)',
              color: 'var(--fg)',
            },
          }}
        />
      </SelectionProvider>
    </QueryClientProvider>
  )
}
