import { apiRequest } from '@/lib/api-client'
import type { LoginRequest, RegisterRequest, TokenResponse, UserRead } from '@/types/auth'

export function login(payload: LoginRequest): Promise<TokenResponse> {
  return apiRequest<TokenResponse>('/auth/login', { method: 'POST', body: payload, skipAuth: true })
}

export function register(payload: RegisterRequest): Promise<UserRead> {
  return apiRequest<UserRead>('/auth/register', { method: 'POST', body: payload, skipAuth: true })
}

export function getCurrentUser(): Promise<UserRead> {
  return apiRequest<UserRead>('/auth/me')
}
