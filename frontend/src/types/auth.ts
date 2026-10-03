export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  full_name: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export type Role = 'admin' | 'clinician'

export interface UserRead {
  id: string
  email: string
  full_name: string
  role: Role
  /** Signed in with an admin-issued one-time password: must choose a new one first. */
  must_change_password: boolean
  /** Finished or skipped the first-run guided tour. */
  tour_completed: boolean
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
}

/** A row on the admin Users page. */
export interface AdminUser {
  id: string
  email: string
  full_name: string
  role: Role
  is_active: boolean
  must_change_password: boolean
  last_login_at: string | null
  created_at: string
}

export interface AdminUserCreate {
  email: string
  full_name: string
  role: Role
}

export interface AdminUserUpdate {
  role?: Role
  is_active?: boolean
}

/** The one-time password is in this response only — it is never shown again. */
export interface OneTimePasswordResponse {
  user: AdminUser
  one_time_password: string
}
