/**
 * window.electron 由 webrender 的 browser-bridge 实现（普通网页宿主），
 * 形状与 Electron preload 暴露的 ipcRenderer 接口保持一致。
 */
/* eslint-disable @typescript-eslint/no-explicit-any -- 与 Electron IpcRenderer 宽泛签名对齐 */
export {}

declare global {
  interface Window {
    electron: {
      ipcRenderer: {
        invoke(channel: string, ...args: any[]): Promise<any>
        send(channel: string, ...args: any[]): void
        on(channel: string, listener: (event: unknown, ...args: any[]) => void): void
        once(channel: string, listener: (event: unknown, ...args: any[]) => void): void
        removeAllListeners(channel: string): void
      }
      webFrame: unknown
      process: { platform: string; versions: Record<string, string> }
    }
    api: {
      getFolder(filePath: string): string
    }
    __apiOnlyMode: boolean
    __hostMode?: 'electron' | 'web'
  }
}
