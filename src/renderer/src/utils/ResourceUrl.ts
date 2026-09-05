/**
 * 资源 URL 构造。
 *
 * - Electron（旧桌面模式）：走 mss:// 自定义协议
 * - Web 宿主（无头渲染框架）：走 Node 宿主的静态路由 /resources/builtin/*
 */
export function isWebHost(): boolean {
  return (globalThis as { __hostMode?: string }).__hostMode === 'web'
}

export function builtinResourceUrl(subPath: string): string {
  if (isWebHost()) {
    return `/resources/builtin/${subPath}`
  }
  return `mss://builtin/${subPath}`
}

export function externalStoryResourceUrl(storyFolder: string, subPath: string): string {
  if (isWebHost()) {
    // Web 宿主只服务内置资源；外部剧本目录不支持
    return `/resources/builtin/${subPath}`
  }
  return `mss://load-file/${storyFolder}/${subPath}`
}
