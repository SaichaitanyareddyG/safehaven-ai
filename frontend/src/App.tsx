import { QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom'

import { Toaster } from '@/components/ui/sonner'
import { AuthProvider } from '@/lib/auth-context'
import { queryClient } from '@/lib/query-client'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { LoginPage } from '@/pages/LoginPage'
import { PatientListPage } from '@/pages/PatientListPage'
import { PatientDetailPage } from '@/pages/PatientDetailPage'
import { InstructionWorkflowPage } from '@/pages/InstructionWorkflowPage'
import { MedicationVerificationPage } from '@/pages/MedicationVerificationPage'
import { SafetyAlertsPage } from '@/pages/SafetyAlertsPage'
import { ScanBandPage } from '@/pages/ScanBandPage'
import { DevicesPage } from '@/pages/DevicesPage'
import { PatientCarePage } from '@/pages/PatientCarePage'
import { ChangePasswordPage } from '@/pages/ChangePasswordPage'
import { UsersPage } from '@/pages/UsersPage'
import { SetPasswordPage } from '@/pages/SetPasswordPage'
import { ForgotPasswordPage } from '@/pages/ForgotPasswordPage'

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Router>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            {/* Signed in but not behind ProtectedRoute: a one-time password lands here first */}
            <Route path="/change-password" element={<ChangePasswordPage />} />
            {/* Public: an invite or reset link, and asking for one */}
            <Route path="/set-password" element={<SetPasswordPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            {/* Public, token-gated — no clinician session, must never sit behind ProtectedRoute */}
            <Route path="/care" element={<PatientCarePage />} />
            <Route
              path="/patients"
              element={
                <ProtectedRoute>
                  <PatientListPage />
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
        </Router>
        {/* Top centre: an urgent alert must not hide in a corner, least of all on a phone. */}
        <Toaster richColors position="top-center" closeButton />
      </AuthProvider>
    </QueryClientProvider>
  )
}
