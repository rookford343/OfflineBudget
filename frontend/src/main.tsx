import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider, MutationCache, QueryCache } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'
import { initTheme } from './store/theme.ts'
import { publishAppError, describeError } from './lib/errorBus.ts'
import ErrorToaster from './components/ErrorToaster.tsx'

initTheme()

// Global error surfacing, wired at the cache level rather than per call site.
// The app has ~99 useMutation calls and only a handful ever defined onError,
// so a failed save used to be completely silent -- the UI just didn't change.
// MutationCache/QueryCache onError fire for EVERY mutation and query, and a
// local onError on an individual call still runs alongside this, so existing
// bespoke handling keeps working.
const mutationCache = new MutationCache({
  onError: (error) => publishAppError(describeError(error)),
})

const queryCache = new QueryCache({
  onError: (error, query) => {
    // Background refetches of already-cached data fail invisibly on purpose:
    // the screen still shows good data, and toasting every transient blip
    // while a laptop wakes from sleep would be noise, not signal. Only an
    // outright failure to load (nothing cached to fall back on) is worth
    // interrupting for.
    if (query.state.data !== undefined) return
    publishAppError(describeError(error))
  },
})

const queryClient = new QueryClient({
  mutationCache,
  queryCache,
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      <ErrorToaster />
    </QueryClientProvider>
  </StrictMode>,
)
