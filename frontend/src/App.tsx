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
import { PatientCarePage } from '@/pages/PatientCarePage'

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Router>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
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
            <Route path="/" element={<Navigate to="/patients" replace />} />
            <Route path="*" element={<Navigate to="/patients" replace />} />
          </Routes>
        </Router>
        <Toaster />
      </AuthProvider>
    </QueryClientProvider>
  )
}
