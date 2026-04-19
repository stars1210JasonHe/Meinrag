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
          theme="dark"
          toastOptions={{
            style: {
              background: 'hsl(222 47% 12%)',
              border: '1px solid hsl(217 33% 17%)',
              color: 'hsl(210 40% 98%)',
            },
          }}
        />
      </SelectionProvider>
    </QueryClientProvider>
  )
}
