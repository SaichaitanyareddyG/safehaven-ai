import { clearToken, getToken } from '@/lib/auth-storage'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

const NETWORK_ERROR_MESSAGE = "Couldn't reach SafeHaven — check your connection and try again."

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  // Accepts any params-shaped object — call sites pass typed interfaces (e.g.
  // ListPatientsParams) whose optional string/number fields don't structurally
  // satisfy an indexed Record type, so this stays intentionally loose.
  params?: object
  /** /auth/login and /auth/register run before a token exists. */
  skipAuth?: boolean
}

function buildUrl(path: string, params?: RequestOptions['params']): string {
  const url = new URL(path, API_BASE_URL)
  if (params) {
    for (const [key, value] of Object.entries(params as Record<string, string | number | undefined>)) {
      if (value !== undefined) url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const data = await response.json()
    if (typeof data.detail === 'string') return data.detail
    if (Array.isArray(data.detail)) {
      // FastAPI/Pydantic 422 validation errors
      return data.detail.map((e: { msg?: string }) => e.msg).join('; ')
    }
    return response.statusText
  } catch {
    return response.statusText
  }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, params, skipAuth = false } = options

  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (!skipAuth) {
    const token = getToken()
    if (token) headers['Authorization'] = `Bearer ${token}`
  }

  const send = () =>
    fetch(buildUrl(path, params), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })

  let response: Response
  try {
    response = await send()
  } catch {
    // The request never reached the server (a phone switching networks, a
    // sleeping tab): the browser only says "Failed to fetch". Requests that
    // are safe to repeat get one quiet retry; a POST is never resent, since
    // it could create something twice.
    if (method === 'POST') throw new ApiError(0, NETWORK_ERROR_MESSAGE)
    try {
      await new Promise((resolve) => setTimeout(resolve, 800))
      response = await send()
    } catch {
      throw new ApiError(0, NETWORK_ERROR_MESSAGE)
    }
  }

  if (response.status === 401 && !skipAuth) {
    clearToken()
    window.location.assign('/login')
    throw new ApiError(401, 'Session expired')
  }

  if (!response.ok) {
    throw new ApiError(response.status, await extractErrorMessage(response))
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
