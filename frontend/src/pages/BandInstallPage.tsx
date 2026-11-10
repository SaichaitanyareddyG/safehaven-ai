import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, CheckCircle2, Cpu, Usb } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'

import { getCurrentFirmware } from '@/api/safety-monitoring'
import { AppLayout } from '@/components/AppLayout'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  browserCanInstall,
  InstallError,
  installOnBand,
  type InstallProgress,
} from '@/features/safety-monitoring/band-installer'
import { ApiError } from '@/lib/api-client'
import { useAuth } from '@/lib/auth-context'

const STAGE_TEXT: Record<InstallProgress['stage'], string> = {
  downloading: 'Downloading the firmware…',
  connecting: 'Connecting to the band…',
  erasing: 'Erasing the band. This can take up to a minute…',
  writing: 'Installing…',
  restarting: 'Restarting the band…',
}

type State =
  | { kind: 'idle' }
  | { kind: 'busy'; progress: InstallProgress }
  | { kind: 'done'; version: string }
  | { kind: 'failed'; message: string }

/** Admins: install SafeHaven on a new band over USB, from the browser. The
 *  one step that needs a cable (firmware/NEW_BAND_SETUP.md); everything after
 *  it is over Wi-Fi. */
export function BandInstallPage() {
  const { user } = useAuth()
  const [eraseFirst, setEraseFirst] = useState(true)
  const [state, setState] = useState<State>({ kind: 'idle' })
  const [log, setLog] = useState<string[]>([])
  const logRef = useRef<string[]>([])
  const supported = browserCanInstall()
  const current = useQuery({
    queryKey: ['firmware-current'],
    queryFn: getCurrentFirmware,
    enabled: user?.role === 'admin',
    retry: false,
  })

  if (user && user.role !== 'admin') return <Navigate to="/devices" replace />

  const busy = state.kind === 'busy'

  async function install() {
    logRef.current = []
    setLog([])
    setState({ kind: 'busy', progress: { stage: 'downloading' } })
    try {
      const release = await installOnBand({
        eraseFirst,
        onProgress: (progress) => setState({ kind: 'busy', progress }),
        onLog: (line) => {
          logRef.current = [...logRef.current.slice(-300), line]
          setLog(logRef.current)
        },
      })
      setState({ kind: 'done', version: release.version })
    } catch (error) {
      const message =
        error instanceof InstallError || error instanceof ApiError
          ? error.message
          : 'The install stopped part-way. Unplug the band, plug it back in, and try again. The band is not harmed: it can always be installed again.'
      setState({ kind: 'failed', message })
    }
  }

  return (
    <AppLayout>
      <Link
        to="/devices"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Bands
      </Link>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Install on a new band</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          A new band comes with the maker's own software. Install SafeHaven once over a USB cable, here in the
          browser. After that the band joins Wi-Fi, pairs and updates itself without a cable.
        </p>
      </div>

      {!supported && (
        <Alert variant="destructive" className="mb-6 max-w-2xl" data-testid="install-unsupported">
          <AlertDescription>
            This browser cannot talk to USB devices. Open this page in <strong>Chrome</strong> or{' '}
            <strong>Edge</strong> on a computer (Windows, Mac or Linux). Phones and Safari cannot do this step.
          </AlertDescription>
        </Alert>
      )}

      <ol className="max-w-2xl space-y-4 text-sm">
        <li className="flex gap-3">
          <Step n={1} />
          <div>
            <p className="font-medium">Plug the band into this computer</p>
            <p className="text-muted-foreground">
              Use a USB-C cable that carries data (some charging-only cables don't). The band can be off.
            </p>
          </div>
        </li>
        <li className="flex gap-3">
          <Step n={2} />
          <div className="flex-1 space-y-3">
            <p className="font-medium">Install</p>
            <p className="text-muted-foreground">
              Click Install, pick the band in the list the browser shows (often “USB JTAG/serial debug unit”), and
              click Connect. It takes about a minute.
            </p>
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4"
                checked={eraseFirst}
                disabled={busy}
                onChange={(e) => setEraseFirst(e.target.checked)}
                data-testid="install-erase"
              />
              <span>
                Erase the band first <span className="text-muted-foreground">(recommended for a new band)</span>
                <span className="block text-xs text-muted-foreground">
                  Untick only to reinstall a band that is already paired: erasing also removes its pairing and Wi-Fi,
                  and it has to be paired again.
                </span>
              </span>
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={install} disabled={!supported || busy || !current.data} data-testid="install-start">
                <Usb className="h-4 w-4" />
                {busy ? 'Installing…' : 'Install'}
              </Button>
              {current.data ? (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <Cpu className="h-3.5 w-3.5" />
                  SafeHaven {current.data.version}
                </span>
              ) : current.isError ? (
                <span className="text-xs text-destructive">
                  {current.error instanceof ApiError ? current.error.message : 'Could not reach the server'}
                </span>
              ) : null}
            </div>

            {state.kind === 'busy' && (
              <div className="space-y-1" role="status" data-testid="install-progress">
                <p>
                  {STAGE_TEXT[state.progress.stage]}
                  {state.progress.percent !== undefined && ` ${state.progress.percent}%`}
                </p>
                {state.progress.percent !== undefined && (
                  <div className="h-2 w-full overflow-hidden rounded bg-muted">
                    <div className="h-full bg-primary transition-[width]" style={{ width: `${state.progress.percent}%` }} />
                  </div>
                )}
                <p className="text-xs text-muted-foreground">Keep the band plugged in and this tab open.</p>
              </div>
            )}
            {state.kind === 'failed' && (
              <Alert variant="destructive" data-testid="install-failed">
                <AlertDescription>{state.message}</AlertDescription>
              </Alert>
            )}
            {state.kind === 'done' && (
              <Alert data-testid="install-done">
                <CheckCircle2 className="h-4 w-4" />
                <AlertDescription>
                  SafeHaven {state.version} is installed. Unplug the band. If its screen stays dark, click the{' '}
                  <strong>side button</strong> once to start it.
                </AlertDescription>
              </Alert>
            )}
          </div>
        </li>
        <li className="flex gap-3">
          <Step n={3} />
          <div>
            <p className="font-medium">Connect it to Wi-Fi and pair it</p>
            <p className="text-muted-foreground">
              If the band says it has no network, hold its side button for 5 seconds and set the Wi-Fi from a phone.
              Once online it shows a 6-digit code: on{' '}
              <Link to="/devices" className="text-primary underline-offset-2 hover:underline">
                Bands
              </Link>
              , click <strong>Add device</strong> and type it in.
            </p>
          </div>
        </li>
      </ol>

      <details className="mt-8 max-w-2xl text-sm">
        <summary className="cursor-pointer text-muted-foreground">If it doesn't connect</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
          <li>Try another cable or USB port. Many cables only charge.</li>
          <li>
            Unplug the band, hold its side button, and plug it back in while holding. Release after 2 seconds, then
            click Install.
          </li>
          <li>Close any other program or tab that might be using the band (Arduino, PlatformIO, another installer).</li>
        </ul>
        {log.length > 0 && (
          <pre className="mt-3 max-h-64 overflow-auto rounded bg-muted p-3 text-xs" data-testid="install-log">
            {log.join('\n')}
          </pre>
        )}
      </details>
    </AppLayout>
  )
}

function Step({ n }: { n: number }) {
  return (
    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
      {n}
    </span>
  )
}
