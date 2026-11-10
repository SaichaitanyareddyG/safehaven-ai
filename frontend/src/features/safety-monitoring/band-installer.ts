/** Install SafeHaven on a band over USB, from the browser (Web Serial, Chrome
 *  or Edge on a computer). The same four pieces `pio run -t upload` writes:
 *
 *    0x0      bootloader (with automatic rollback for Wi-Fi updates)
 *    0x8000   partition table (two app slots, so later updates go over Wi-Fi)
 *    0xe000   OTA data, blank: the band starts from the first slot
 *    0x10000  the app: the published release, downloaded by an admin
 *
 *  The first three never change with a release and hold no secrets, so they
 *  ship with the dashboard (public/band-install/, copied from the
 *  m5sticks3-lowpower build). The app carries the setup Wi-Fi settings, so it
 *  comes from the server, admins only. */
import { downloadFirmwareImage, getCurrentFirmware } from '@/api/safety-monitoring'
import { md5Hex } from '@/lib/md5'
import type { FirmwareCurrent } from '@/types/safety-monitoring'

export type InstallStage = 'connecting' | 'downloading' | 'erasing' | 'writing' | 'restarting'

export interface InstallProgress {
  stage: InstallStage
  /** 0-100 while writing, otherwise undefined. */
  percent?: number
}

export class InstallError extends Error {}

/** Espressif's USB vendor ID: the band's own USB port. */
const ESPRESSIF_USB_VENDOR = 0x303a

const FIXED_PARTS = [
  { path: '/band-install/bootloader.bin', address: 0x0 },
  { path: '/band-install/partition-table.bin', address: 0x8000 },
  { path: '/band-install/ota_data_initial.bin', address: 0xe000 },
]
const APP_ADDRESS = 0x10000

export function browserCanInstall(): boolean {
  return typeof navigator !== 'undefined' && 'serial' in navigator
}

async function sha256Hex(data: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', data as Uint8Array<ArrayBuffer>)
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}

async function fetchFixedPart(path: string): Promise<Uint8Array> {
  const response = await fetch(path, { cache: 'no-store' })
  if (!response.ok) throw new InstallError(`The installer is missing a file (${path}). Reload the page.`)
  return new Uint8Array(await response.arrayBuffer())
}

/** Asks the browser for the band's port first: it must be called from a click. */
export async function installOnBand(options: {
  eraseFirst: boolean
  onProgress: (progress: InstallProgress) => void
  onLog: (line: string) => void
}): Promise<FirmwareCurrent> {
  const { eraseFirst, onProgress, onLog } = options
  if (!browserCanInstall()) throw new InstallError('This browser cannot talk to USB devices. Use Chrome or Edge on a computer.')

  // The browser's port chooser, showing only Espressif devices.
  let port: SerialPort
  try {
    port = await navigator.serial.requestPort({ filters: [{ usbVendorId: ESPRESSIF_USB_VENDOR }] })
  } catch {
    throw new InstallError('No band was chosen. Plug the band in with a data cable, then try again.')
  }

  onProgress({ stage: 'downloading' })
  const release = await getCurrentFirmware()
  const [app, ...fixed] = await Promise.all([
    downloadFirmwareImage(release.id),
    ...FIXED_PARTS.map((part) => fetchFixedPart(part.path)),
  ])
  if (app.length !== release.size || (await sha256Hex(app)) !== release.sha256) {
    throw new InstallError('The firmware download was damaged. Try again.')
  }

  const { ESPLoader, Transport } = await import('esptool-js')
  const transport = new Transport(port, false)
  try {
    onProgress({ stage: 'connecting' })
    const loader = new ESPLoader({
      transport,
      // The band's port is USB, not a serial chip: speed settings change
      // nothing, and keeping them equal avoids reopening the port.
      baudrate: 921600,
      romBaudrate: 921600,
      terminal: {
        clean: () => undefined,
        writeLine: (line: string) => onLog(line),
        write: (text: string) => onLog(text),
      },
    })
    let chip: string
    try {
      chip = await loader.main()
    } catch {
      throw new InstallError(
        'The band did not answer. Unplug it, hold its side button while plugging it back in, then try again.',
      )
    }
    if (!chip.startsWith('ESP32-S3')) {
      throw new InstallError(`This is not a SafeHaven band (it reports ${chip}). Nothing was written.`)
    }

    if (eraseFirst) {
      onProgress({ stage: 'erasing' })
      await loader.eraseFlash()
    }
    const files = [
      ...FIXED_PARTS.map((part, i) => ({ data: fixed[i], address: part.address })),
      { data: app, address: APP_ADDRESS },
    ]
    const totalBytes = files.reduce((sum, f) => sum + f.data.length, 0)
    const doneBefore = files.map((_, i) => files.slice(0, i).reduce((sum, f) => sum + f.data.length, 0))
    onProgress({ stage: 'writing', percent: 0 })
    await loader.writeFlash({
      fileArray: files,
      // Keep what each image already says (the build's DIO, 80 MHz, 8 MB).
      flashMode: 'keep',
      flashFreq: 'keep',
      flashSize: 'keep',
      eraseAll: false,
      compress: true,
      // The band reads each piece back and its MD5 must match, or this throws.
      calculateMD5Hash: md5Hex,
      reportProgress: (fileIndex, written, total) => {
        const share = files[fileIndex].data.length / totalBytes
        const before = doneBefore[fileIndex] / totalBytes
        onProgress({ stage: 'writing', percent: Math.min(100, Math.round((before + share * (written / total)) * 100)) })
      },
    })
    onProgress({ stage: 'restarting' })
    await loader.after('hard_reset')
    return release
  } finally {
    await transport.disconnect().catch(() => undefined)
  }
}
