# MySekaiStoryteller-API 纯 API 渲染宿主 — 部署指南

本项目已从 Electron 桌面应用重构为**无头纯 API 渲染框架**：Live2D 渲染跑在无头 Chrome
（Playwright 驱动）里，Node 宿主提供 HTTP API、静态资源托管与 ffmpeg 编码。无需桌面环境、
无需 Xorg/Xvfb，Linux 服务器 + NVIDIA 驱动即可获得硬件加速渲染与 NVENC 编码。

## 架构

```
Node 20 宿主（单进程 + N 个无头浏览器渲染工作进程）
├─ :9881  VideoApiServer   视频导出 API（端点与旧版完全一致）
├─ :9881  静态托管          / 渲染页面 · /resources/* · /apifile/*
├─ :9881  桥接层 /bridge/*  invoke · 二进制写盘 · TTS/翻译代理 · WebSocket
└─ RenderPool             N 个无头 Chrome 页面（每页独立 WebGL 上下文）
```

导出数据流（与旧版语义一致）：
`POST /api/v1/export` → 队列（≤2 并发）→ 渲染页面 MediaRecorder 录 WebM（分块回传写盘）
→ Web Audio 混音 WAV → ffmpeg 转码/合流 MP4 → `downloadUrl` 供下载。
AstrBot 插件（[astrbot_plugin_msst](https://github.com/yonglanws/astrbot_plugin_msst)，
独立仓库）**零改动兼容**。

## 依赖

| 组件                     | 说明                                                                                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Node.js ≥ 20             | 推荐 22 LTS                                                                                                                                       |
| Chrome / Edge / Chromium | 渲染工作进程。自动按 `render.browserChannels` 顺序探测（默认 msedge → chrome → chromium）；无系统浏览器时先执行 `npx playwright install chromium` |
| ffmpeg                   | 编码器。优先 `MSS_FFMPEG_PATH`，其次 npm 包 `ffmpeg-static`（安装时自动下载），最后 PATH                                                          |
| NVIDIA 驱动（服务器）    | `nvidia-smi` 可用即可，**不需要 Xorg / Xvfb / 桌面环境**                                                                                          |

## 构建与启动

```bash
git clone <repo> && cd MySekaiStoryteller-API
npm ci
npx playwright install chromium   # 服务器上没有 Edge/Chrome 时需要
cp config.example.yaml config.yaml
vim config.yaml                   # 至少看一下 server/video/render 节
npm run build                     # typecheck + vite(webrenderer) + tsc(host)
npm start                         # node out-host/host/main.js
```

### 资源准备

仓库**不附带**渲染资源，需自行把 Live2D 模型、背景图、BGM、示例剧本放入资源根
（默认 `resources/`，可用 `MSS_RESOURCE_DIR` 指向他处）。
目录结构与登记方式见 [resources/README.md](../resources/README.md)。

## 配置（config.yaml）

所有配置集中在仓库根的 `config.yaml`（从 `config.example.yaml` 复制，每个字段都有中文注释）。
**`config.yaml` 不入库**，升级代码不会覆盖你的配置。

| 节       | 内容                                                                                |
| -------- | ----------------------------------------------------------------------------------- |
| `server` | 端口、监听地址                                                                      |
| `video`  | 分辨率、帧率、CRF、渲染超采样、音频码率、**编码器**（auto/nvenc/amf/intel/libx264） |
| `render` | worker 数、页面回收周期、浏览器探测顺序、附加 Chrome 参数、Linux GPU 开关           |
| `paths`  | 输出目录（apifile）、资源根（resources）、webrenderer 产物目录                      |
| `tts`    | GPT-SoVITS 地址、启停、全局/角色参考音频与权重                                      |
| `bgm`    | 启停、BGM 路径（相对资源根，如 `audio/bgm/bg1.mp3`）、音量                          |

环境变量可覆盖同名配置（适合 systemd/容器注入），见下表。

### 环境变量

| 变量                                                                                          | 覆盖的配置                    | 说明                                    |
| --------------------------------------------------------------------------------------------- | ----------------------------- | --------------------------------------- |
| `MSS_PORT` / `MSS_HOST`                                                                       | `server.port` / `server.host` | 监听                                    |
| `MSS_VIDEO_WIDTH` / `MSS_VIDEO_HEIGHT` / `MSS_VIDEO_FPS` / `MSS_VIDEO_CRF`                    | `video.*`                     | 输出参数                                |
| `MSS_FFMPEG_ENCODER`                                                                          | `video.encoder`               | auto/nvenc/amf/intel/libx264            |
| `MSS_WORKERS` / `MSS_WORKER_RECYCLE_EXPORTS`                                                  | `render.*`                    | 渲染池                                  |
| `MSS_BROWSER_CHANNELS` / `MSS_BROWSER_EXECUTABLE` / `MSS_CHROME_ARGS` / `MSS_LINUX_GPU_ANGLE` | `render.*`                    | 浏览器                                  |
| `MSS_OUTPUT_DIR` / `MSS_RESOURCE_DIR` / `MSS_WEB_RENDERER_DIR`                                | `paths.*`                     | 路径                                    |
| `MSS_FFMPEG_PATH`                                                                             | （独立）                      | 显式指定 ffmpeg 可执行文件              |
| `MSS_LOG_LEVEL`                                                                               | `logLevel`                    | silly/trace/debug/info/warn/error/fatal |

启动后自检：

```bash
curl http://127.0.0.1:9881/api/v1/health
```

关注返回中的 `renderPool` 字段：

```json
{
  "renderPool": {
    "readyWorkers": 1,
    "webglRenderers": [{ "workerId": "w1", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX ...)" }]
  }
}
```

**`renderer` 必须是真实 GPU**（如 `ANGLE (NVIDIA ...)`）。若出现 `SwiftShader` / `llvmpipe`
字样说明 WebGL 落到了软件渲染，导出会慢 5-10 倍——此时调整浏览器启动参数（见下方
`MSS_CHROME_ARGS`）。

## 端到端测试

```bash
npm run e2e                        # 示例故事导出 + ffprobe 断言
node scripts/test-parallel.mjs 2   # 双任务并发导出验证
```

E2E 默认使用 `resources/stories/multi-character-demo.sekai-story.json`（随资源包提供，
见上方「资源准备」），并会把故事中缺失的模型变体自动替换为本机实际存在的资源。

## systemd 部署（Linux 裸机 + NVIDIA）

`deploy/mysekai-host.service`：

```ini
[Unit]
Description=MySekaiStoryteller-API Pure-API Render Host
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/opt/MySekaiStoryteller-API
Environment=MSS_FFMPEG_ENCODER=auto
Environment=MSS_WORKERS=2
ExecStart=/usr/bin/node out-host/host/main.js
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

注意与旧版 Electron 部署的差异：**不再需要** ExecStartPre 启动 Xorg、不再需要
`DISPLAY` / `__GLX_VENDOR_LIBRARY_NAME` 等环境变量。

### NVENC 验证三步

```bash
# 1. ffmpeg 有 nvenc 编码器
ffmpeg -hide_banner -encoders | grep nvenc

# 2. health 返回的 WebGL renderer 是 NVIDIA（非 SwiftShader）
curl -s http://127.0.0.1:9881/api/v1/health | grep -o '"renderer":"[^"]*"'

# 3. 导出期间 GPU 在跑
nvidia-smi dmon -s um      # sm/mem 占用应随导出波动；日志可见 "using encoder: h264_nvenc"
```

### 无 GPU WebGL 时的参数调优

若 health 显示 SwiftShader，按顺序尝试（写进 config.yaml 的
`render.extraChromeArgs`，或用 `MSS_CHROME_ARGS` 注入）：

```text
--use-angle=gl            # 方案 A（Linux NVIDIA 常用）
--use-angle=vulkan        # 方案 B（较新驱动）
--use-angle=swiftshader   # 仅用于确认软件渲染症状
```

## 安全提示

API 监听 `0.0.0.0` 且无鉴权（仅 10 次/分钟 IP 限流）。内网使用即可；公网暴露请前置
反向代理（nginx/caddy）加鉴权，并关闭 `/bridge`、`/apifile` 的外部访问。
