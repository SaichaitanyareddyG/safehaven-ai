import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Mic, Plus, Square } from 'lucide-react'
import { useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

import { createInstruction, transcribeDictation } from '@/api/instructions'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api-client'
import type { DictationWarning } from '@/types/instructions'

const schema = z.object({
  text: z.string().trim().min(1, 'Enter the clinical instruction text'),
})

type FormValues = z.infer<typeof schema>

// An instruction is a sentence or two — a long recording means something went
// wrong (forgotten stop, ambient conversation), and both are worth cutting off
// rather than transcribing.
const MAX_RECORDING_MS = 2 * 60 * 1000

const canRecord = typeof window !== 'undefined' && typeof window.MediaRecorder !== 'undefined'

export function CreateInstructionDialog({ patientId }: { patientId: string }) {
  const [open, setOpen] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [warnings, setWarnings] = useState<DictationWarning[]>([])
  // Provenance only (recorded as CaptureMethod server-side) — never changes
  // how the text is validated or what the clinician must do with it.
  const [wasDictated, setWasDictated] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const mutation = useMutation({
    mutationFn: (values: FormValues) => createInstruction(patientId, values.text, wasDictated),
    onSuccess: (instruction) => {
      queryClient.invalidateQueries({ queryKey: ['patient-instructions', patientId] })
      closeAndReset()
      navigate(`/instructions/${instruction.id}`)
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to create instruction')
    },
  })

  function closeAndReset() {
    setOpen(false)
    reset()
    setWarnings([])
    setWasDictated(false)
    setIsRecording(false)
    setIsTranscribing(false)
  }

  async function startRecording() {
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      toast.error('Microphone unavailable — please type the instruction instead')
      return
    }

    const recorder = new MediaRecorder(stream)
    const chunks: Blob[] = []
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data)
    }
    recorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop())
      setIsRecording(false)
      setIsTranscribing(true)
      try {
        const result = await transcribeDictation(new Blob(chunks, { type: recorder.mimeType }))
        if (!result.text) {
          toast.error("Didn't catch anything — please try again or type it")
        } else {
          // Appended to whatever is already there, never replacing it — a
          // clinician may dictate an addition to text they already typed.
          const existing = getValues('text') ?? ''
          setValue('text', existing ? `${existing.trim()} ${result.text}` : result.text, {
            shouldValidate: true,
          })
          setWasDictated(true)
        }
        setWarnings(result.warnings)
      } catch {
        // Never fabricate or partially apply a transcript — leave the
        // textarea untouched so typing still works exactly as before.
        toast.error('Could not transcribe the recording — please type it instead')
      } finally {
        setIsTranscribing(false)
      }
    }

    recorderRef.current = recorder
    recorder.start()
    setIsRecording(true)
    window.setTimeout(() => {
      if (recorder.state === 'recording') recorder.stop()
    }, MAX_RECORDING_MS)
  }

  function stopRecording() {
    recorderRef.current?.stop()
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : closeAndReset())}>
      <DialogTrigger asChild>
        <Button data-testid="instruction-new-button">
          <Plus className="h-4 w-4" />
          New Instruction
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Enter a clinical instruction</DialogTitle>
          <DialogDescription>
            Write it exactly as you would for the chart. AI will analyze it in the next step — nothing is sent to
            the patient yet.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((values) => mutation.mutate(values))} noValidate>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="text">Clinical instruction</Label>
              {canRecord &&
                (isRecording ? (
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    onClick={stopRecording}
                    data-testid="dictate-stop-button"
                  >
                    <Square className="h-4 w-4" />
                    Stop
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={isTranscribing}
                    onClick={startRecording}
                    data-testid="dictate-button"
                  >
                    <Mic className="h-4 w-4" />
                    {isTranscribing ? 'Transcribing…' : 'Dictate'}
                  </Button>
                ))}
            </div>
            <Textarea
              id="text"
              rows={4}
              placeholder="e.g. Take Metoprolol 25 mg orally twice daily with food."
              {...register('text')}
            />
            {isRecording && (
              <p className="text-sm text-muted-foreground" data-testid="dictate-recording-indicator">
                Recording… press Stop when you're finished.
              </p>
            )}
            {wasDictated && !isRecording && !isTranscribing && (
              <p className="text-sm text-muted-foreground" data-testid="dictate-review-notice">
                Dictated draft — read it back before creating. Nothing is submitted until you press Create.
              </p>
            )}
            {errors.text && <p className="text-sm text-destructive">{errors.text.message}</p>}
          </div>

          {warnings.length > 0 && (
            <div
              className="space-y-2 rounded-lg border-2 border-amber-400 bg-amber-50 p-3 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
              data-testid="dictation-warnings"
            >
              <p className="flex items-center gap-2 text-sm font-semibold">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                Check these before creating
              </p>
              <ul className="space-y-1 text-sm">
                {warnings.map((warning, index) => (
                  <li key={index} data-testid="dictation-warning">
                    {warning.message}
                    <span className="mt-0.5 block font-mono text-xs opacity-70">{warning.excerpt}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <DialogFooter>
            <Button
              type="submit"
              disabled={isSubmitting || mutation.isPending || isRecording || isTranscribing}
              data-testid="instruction-create-submit"
            >
              {mutation.isPending ? 'Creating…' : 'Create instruction'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
