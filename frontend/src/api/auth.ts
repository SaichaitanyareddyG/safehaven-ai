import { apiRequest } from '@/lib/api-client'
import type {
  ChangePasswordRequest,
  LoginRequest,
  PasswordLinkInfo,
  RegisterRequest,
  TokenResponse,
  UserRead,
} from '@/types/auth'

export function login(payload: LoginRequest): Promise<TokenResponse> {
  return apiRequest<TokenResponse>('/auth/login', { method: 'POST', body: payload, skipAuth: true })
}

export function register(payload: RegisterRequest): Promise<UserRead> {
  return apiRequest<UserRead>('/auth/register', { method: 'POST', body: payload, skipAuth: true })
}

export function getCurrentUser(): Promise<UserRead> {
  return apiRequest<UserRead>('/auth/me')
}

export function changePassword(payload: ChangePasswordRequest): Promise<void> {
  return apiRequest<void>('/auth/change-password', { method: 'POST', body: payload })
}

export function completeTour(): Promise<void> {
  return apiRequest<void>('/auth/tour-complete', { method: 'POST' })
}

export function forgotPassword(email: string): Promise<void> {
  return apiRequest<void>('/auth/forgot-password', { method: 'POST', body: { email }, skipAuth: true })
}

export function getPasswordLink(token: string): Promise<PasswordLinkInfo> {
  return apiRequest<PasswordLinkInfo>(`/auth/password-link/${encodeURIComponent(token)}`, { skipAuth: true })
}

/** Choose a password from an invite or reset link; signs straight in. */
export function setPasswordFromLink(token: string, newPassword: string): Promise<TokenResponse> {
  return apiRequest<TokenResponse>('/auth/set-password', {
    method: 'POST',
    body: { token, new_password: newPassword },
    skipAuth: true,
  })
}
