import { apiRequest } from '@/lib/api-client'
import type { AdminUser, AdminUserCreate, AdminUserUpdate, OneTimePasswordResponse } from '@/types/auth'

export function listUsers(): Promise<AdminUser[]> {
  return apiRequest<AdminUser[]>('/admin/users')
}

export function createUser(payload: AdminUserCreate): Promise<OneTimePasswordResponse> {
  return apiRequest<OneTimePasswordResponse>('/admin/users', { method: 'POST', body: payload })
}

export function updateUser(id: string, payload: AdminUserUpdate): Promise<AdminUser> {
  return apiRequest<AdminUser>(`/admin/users/${id}`, { method: 'PATCH', body: payload })
}

export function resetUserPassword(id: string): Promise<OneTimePasswordResponse> {
  return apiRequest<OneTimePasswordResponse>(`/admin/users/${id}/reset-password`, { method: 'POST' })
}
