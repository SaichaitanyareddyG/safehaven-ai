import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Globe, Send } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { getCarePlanChat, sendCarePlanChatMessage } from '@/api/patient-chat'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { ChatMessage } from '@/types/patient-chat'

export function PatientChatPanel({ token }: { token: string }) {
  const [isOpen, setIsOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [pendingUserText, setPendingUserText] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const queryKey = ['patient-chat', token]
  const { data } = useQuery({
    queryKey,
    queryFn: () => getCarePlanChat(token),
    enabled: isOpen,
  })

  const mutation = useMutation({
    mutationFn: (text: string) => sendCarePlanChatMessage(token, text),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKey, (existing: { messages: ChatMessage[] } | undefined) => ({
        messages: [...(existing?.messages ?? []), result.patient_message, result.assistant_message],
      }))
    },
    onSettled: () => setPendingUserText(null),
  })

  function handleSend() {
    const text = draft.trim()
    if (!text || mutation.isPending) return
    setDraft('')
    setPendingUserText(text)
    mutation.mutate(text)
  }

  const messages = data?.messages ?? []

  // Keep the newest message in view: on a phone the question, "Thinking…"
  // and the answer otherwise land below the visible part of the box.
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages.length, pendingUserText, mutation.isPending, isOpen])

  return (
    <div className="rounded-2xl border-2 bg-background text-left shadow-sm" data-testid="patient-chat-panel">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="flex w-full items-center justify-between p-6"
        data-testid="patient-chat-toggle"
      >
        <span className="text-2xl font-semibold">Ask a question</span>
        <ChevronDown className={cn('h-5 w-5 transition-transform', isOpen && 'rotate-180')} />
      </button>

      {isOpen && (
        <div className="border-t p-6" data-testid="patient-chat-body">
          <div className="max-h-[60vh] space-y-3 overflow-y-auto" aria-live="polite">
            {messages.length === 0 && !pendingUserText && (
              <p className="text-base text-muted-foreground">
                Ask about your medications or instructions — this only answers from your own approved care plan.
              </p>
            )}
            {messages.map((message) => (
              <ChatBubble key={message.id} message={message} />
            ))}
            {pendingUserText && <ChatBubble message={{ role: 'PATIENT', text: pendingUserText } as ChatMessage} />}
            {mutation.isPending && (
              <p className="flex items-center gap-2 text-base text-muted-foreground" data-testid="patient-chat-thinking">
                <span className="flex gap-1" aria-hidden="true">
                  <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.3s]" />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.15s]" />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/60" />
                </span>
                Thinking…
              </p>
            )}
            <div ref={endRef} />
          </div>

          <div className="mt-4 flex gap-2">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder="Type your question…"
              disabled={mutation.isPending}
              className="flex-1"
              data-testid="patient-chat-input"
            />
            <Button
              onClick={handleSend}
              disabled={mutation.isPending || !draft.trim()}
              data-testid="patient-chat-send"
              size="icon-lg"
              aria-label="Send question"
              className="h-auto min-h-12 w-12"
            >
              <Send className="h-5 w-5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const isPatient = message.role === 'PATIENT'
  const isSafetyReply = !isPatient && (message.emergency_flagged || message.redirect_flagged)

  return (
    <div className={cn('flex', isPatient ? 'justify-end' : 'justify-start')} data-testid="patient-chat-bubble">
      <div
        className={cn(
          'max-w-[85%] rounded-xl px-4 py-2.5 text-base leading-relaxed',
          isPatient
            ? 'bg-primary text-primary-foreground'
            : isSafetyReply
              ? 'border-2 border-amber-400 bg-amber-50 text-amber-950'
              : 'bg-muted',
        )}
      >
        <p>{message.text}</p>
        {message.web_search_used && (
          <p className="mt-1.5 flex items-center gap-1 text-xs text-muted-foreground">
            <Globe className="h-3 w-3" /> Includes general medical reference sources
          </p>
        )}
      </div>
    </div>
  )
}
