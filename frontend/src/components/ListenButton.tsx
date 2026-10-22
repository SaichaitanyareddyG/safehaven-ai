import { Loader2, Pause, Play, RotateCcw, Square, VolumeX } from 'lucide-react'
import { useCallback } from 'react'

import { Button } from '@/components/ui/button'
import { getCarePlanAudio } from '@/api/patient-access'
import { getMyAudio } from '@/api/patient-app'
import { useSpeech } from '@/lib/use-speech'
import type { Language } from '@/types/patients'

/** Reads shown text aloud: with a care-link token, or (asPatient) with the
 *  patient app's own session. */
export function ListenButton({
  text,
  language = 'ENGLISH',
  token,
  asPatient = false,
}: {
  text: string
  language?: Language
  token?: string
  asPatient?: boolean
}) {
  const fetchAudio = useCallback(
    (shown: string) => (asPatient ? getMyAudio(shown) : getCarePlanAudio(token ?? '', shown, language)),
    [asPatient, token, language],
  )
  const { status, play, pause, resume, stop, replay } = useSpeech(text, fetchAudio)

  if (status === 'error') {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <p className="flex items-center gap-2 text-base text-muted-foreground">
          <VolumeX className="h-5 w-5" />
          Audio isn't available right now.
        </p>
        <Button variant="ghost" size="lg" onClick={play} data-testid="listen-retry-button">
          <RotateCcw className="h-5 w-5" />
          Try again
        </Button>
      </div>
    )
  }

  if (status === 'loading') {
    return (
      <Button variant="outline" size="lg" disabled data-testid="listen-button">
        <Loader2 className="h-5 w-5 animate-spin" />
        Loading audio…
      </Button>
    )
  }

  if (status === 'idle') {
    return (
      <Button size="lg" onClick={play} data-testid="listen-button">
        <Play className="h-5 w-5" />
        Listen
      </Button>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="listen-controls">
      {status === 'speaking' ? (
        <Button variant="outline" size="lg" onClick={pause} data-testid="listen-pause-button">
          <Pause className="h-5 w-5" />
          Pause
        </Button>
      ) : (
        <Button variant="outline" size="lg" onClick={resume} data-testid="listen-resume-button">
          <Play className="h-5 w-5" />
          Resume
        </Button>
      )}
      <Button variant="outline" size="lg" onClick={stop} data-testid="listen-stop-button">
        <Square className="h-5 w-5" />
        Stop
      </Button>
      <Button variant="outline" size="lg" onClick={replay} data-testid="listen-replay-button">
        <RotateCcw className="h-5 w-5" />
        Replay
      </Button>
    </div>
  )
}
