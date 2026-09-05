import '../../renderer/assets/main.css'
import { serializeError } from '../../renderer/src/utils/HelperUtils'
import { installBrowserBridge } from './browser-bridge'

async function start(): Promise<void> {
  window.addEventListener('unhandledrejection', (event) => {
    if (event.reason instanceof Error) {
      window.electron.ipcRenderer.send('electron:on-error', serializeError(event.reason))
    }
  })

  await installBrowserBridge()

  const { default: main } = await import('../../renderer/src/app/App')
  await main().catch((error: unknown) => {
    if (error instanceof Error) {
      window.electron.ipcRenderer.send('electron:on-error', serializeError(error))
    }
    throw error
  })
}

void start()
