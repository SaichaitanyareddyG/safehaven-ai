import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/lib/api-client'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status < 500) return false
        return failureCount < 2
      },
      staleTime: 10_000,
    },
    mutations: {
      retry: false,
    },
  },
})
