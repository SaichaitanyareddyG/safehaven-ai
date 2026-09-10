import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Globe, ShieldAlert } from 'lucide-react'

import { getPatientChat } from '@/api/patient-chat'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { ChatMessage } from '@/types/patient-chat'

export function PatientChatTranscript({ patientId }: { patientId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['patient-chat-transcript', patientId],
    queryFn: () => getPatientChat(patientId),
  })

  if (isLoading) {
    return <Skeleton className="h-32 w-full" />
  }

  const messages = data?.messages ?? []

  if (messages.length === 0) {
    return <p className="text-sm text-muted-foreground">This patient hasn't asked anything yet.</p>
  }

  return (
    <div className="space-y-3" data-testid="patient-chat-transcript">
      {messages.map((message) => (
        <TranscriptRow key={message.id} message={message} />
      ))}
    </div>
  )
}

function TranscriptRow({ message }: { message: ChatMessage }) {
  const isPatient = message.role === 'PATIENT'
  return (
    <div className={cn('rounded-lg border p-3', isPatient ? 'bg-muted/30' : 'bg-background')}>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span className="font-semibold uppercase tracking-wide">{isPatient ? 'Patient' : 'Assistant'}</span>
        <span>{new Date(message.created_at).toLocaleString()}</span>
      </div>
      <p className="mt-1 text-sm">{message.text}</p>
      <div className="mt-1.5 flex gap-3">
        {message.emergency_flagged && (
          <span className="flex items-center gap-1 text-xs font-medium text-destructive">
            <ShieldAlert className="h-3 w-3" /> Emergency gate fired
          </span>
        )}
        {message.redirect_flagged && (
          <span className="flex items-center gap-1 text-xs font-medium text-amber-600">
            <AlertTriangle className="h-3 w-3" /> Treatment-change redirect
          </span>
        )}
        {message.web_search_used && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Globe className="h-3 w-3" /> Used trusted-source web search
          </span>
        )}
      </div>
    </div>
  )
}
