import { QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom'

import { Toaster } from '@/components/ui/sonner'
import { AuthProvider } from '@/lib/auth-context'
import { queryClient } from '@/lib/query-client'
import { ProtectedRoute } from '@/components/ProtectedRoute'

// Each page is its own download: a patient opening /my on a phone gets the
// patient app, not the whole staff dashboard (and the barcode scanner).
const LoginPage = lazy(() => import('@/pages/LoginPage').then((m) => ({ default: m.LoginPage })))
const PatientListPage = lazy(() => import('@/pages/PatientListPage').then((m) => ({ default: m.PatientListPage })))
const PatientDetailPage = lazy(() => import('@/pages/PatientDetailPage').then((m) => ({ default: m.PatientDetailPage })))
const InstructionWorkflowPage = lazy(() => import('@/pages/InstructionWorkflowPage').then((m) => ({ default: m.InstructionWorkflowPage })))
const MedicationVerificationPage = lazy(() => import('@/pages/MedicationVerificationPage').then((m) => ({ default: m.MedicationVerificationPage })))
const SafetyAlertsPage = lazy(() => import('@/pages/SafetyAlertsPage').then((m) => ({ default: m.SafetyAlertsPage })))
const ScanBandPage = lazy(() => import('@/pages/ScanBandPage').then((m) => ({ default: m.ScanBandPage })))
const DevicesPage = lazy(() => import('@/pages/DevicesPage').then((m) => ({ default: m.DevicesPage })))
const PatientCarePage = lazy(() => import('@/pages/PatientCarePage').then((m) => ({ default: m.PatientCarePage })))
const ChangePasswordPage = lazy(() => import('@/pages/ChangePasswordPage').then((m) => ({ default: m.ChangePasswordPage })))
const UsersPage = lazy(() => import('@/pages/UsersPage').then((m) => ({ default: m.UsersPage })))
const SetPasswordPage = lazy(() => import('@/pages/SetPasswordPage').then((m) => ({ default: m.SetPasswordPage })))
const ForgotPasswordPage = lazy(() => import('@/pages/ForgotPasswordPage').then((m) => ({ default: m.ForgotPasswordPage })))
const MyPrintPage = lazy(() => import('@/pages/my/MyPrintPage').then((m) => ({ default: m.MyPrintPage })))
const PrintCarePlanPage = lazy(() =>
  import('@/pages/PrintCarePlanPage').then((m) => ({ default: m.PrintCarePlanPage })),
)
const MyAskPage = lazy(() => import('@/pages/my/MyAskPage').then((m) => ({ default: m.MyAskPage })))
const MyCarePage = lazy(() => import('@/pages/my/MyCarePage').then((m) => ({ default: m.MyCarePage })))
const MyHomePage = lazy(() => import('@/pages/my/MyHomePage').then((m) => ({ default: m.MyHomePage })))
const MyMedicinesPage = lazy(() => import('@/pages/my/MyMedicinesPage').then((m) => ({ default: m.MyMedicinesPage })))
const MySignInPage = lazy(() => import('@/pages/my/MySignInPage').then((m) => ({ default: m.MySignInPage })))
const MyVisitsPage = lazy(() => import('@/pages/my/MyVisitsPage').then((m) => ({ default: m.MyVisitsPage })))

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Router>
          <Suspense fallback={<PageLoading />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              {/* Signed in but not behind ProtectedRoute: a one-time password lands here first */}
              <Route path="/change-password" element={<ChangePasswordPage />} />
              {/* Public: an invite or reset link, and asking for one */}
              <Route path="/set-password" element={<SetPasswordPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              {/* Public, token-gated — no clinician session, must never sit behind ProtectedRoute */}
              <Route path="/care" element={<PatientCarePage />} />
              {/* The patient app: its own sign-in and session, never staff's (MyAppLayout guards). */}
              <Route path="/my/sign-in" element={<MySignInPage />} />
              <Route path="/my" element={<MyHomePage />} />
              <Route path="/my/medicines" element={<MyMedicinesPage />} />
              <Route path="/my/visits" element={<MyVisitsPage />} />
              <Route path="/my/care" element={<MyCarePage />} />
              <Route path="/my/ask" element={<MyAskPage />} />
              <Route path="/my/print" element={<MyPrintPage />} />
              <Route path="/my/*" element={<Navigate to="/my" replace />} />
              <Route
                path="/patients"
                element={
                  <ProtectedRoute>
                    <PatientListPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/patients/:patientId/print"
                element={
                  <ProtectedRoute>
                    <PrintCarePlanPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/patients/:patientId"
                element={
                  <ProtectedRoute>
                    <PatientDetailPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/instructions/:instructionId"
                element={
                  <ProtectedRoute>
                    <InstructionWorkflowPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/medication-verification"
                element={
                  <ProtectedRoute>
                    <MedicationVerificationPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/safety-monitoring"
                element={
                  <ProtectedRoute>
                    <SafetyAlertsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/devices"
                element={
                  <ProtectedRoute>
                    <DevicesPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/scan-band"
                element={
                  <ProtectedRoute>
                    <ScanBandPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin/users"
                element={
                  <ProtectedRoute adminOnly>
                    <UsersPage />
                  </ProtectedRoute>
                }
              />
              <Route path="/" element={<Navigate to="/patients" replace />} />
              <Route path="*" element={<Navigate to="/patients" replace />} />
            </Routes>
          </Suspense>
        </Router>
        {/* Top centre: an urgent alert must not hide in a corner, least of all on a phone. */}
        <Toaster richColors position="top-center" closeButton />
      </AuthProvider>
    </QueryClientProvider>
  )
}

function PageLoading() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background" role="status" aria-live="polite">
      <span className="h-8 w-8 animate-spin rounded-full border-4 border-primary/25 border-t-primary" />
      <span className="sr-only">Loading…</span>
    </div>
  )
}
