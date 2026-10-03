import { apiRequest } from '@/lib/api-client'
import type { AdminUser, AdminUserCreate, AdminUserUpdate, InviteResponse } from '@/types/auth'

export function listUsers(): Promise<AdminUser[]> {
  return apiRequest<AdminUser[]>('/admin/users')
}

export function createUser(payload: AdminUserCreate): Promise<InviteResponse> {
  return apiRequest<InviteResponse>('/admin/users', { method: 'POST', body: payload })
}

export function updateUser(id: string, payload: AdminUserUpdate): Promise<AdminUser> {
  return apiRequest<AdminUser>(`/admin/users/${id}`, { method: 'PATCH', body: payload })
}

/** Resends the invite, or sends a reset link if they already have a password. */
export function sendPasswordLink(id: string): Promise<InviteResponse> {
  return apiRequest<InviteResponse>(`/admin/users/${id}/send-link`, { method: 'POST' })
}
