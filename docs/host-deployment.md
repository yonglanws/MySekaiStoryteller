# MySekaiStoryteller 纯 API 渲染宿主 — 部署指南

本项目已从 Electron 桌面应用重构为**无头纯 API 渲染框架**：Live2D 渲染跑在无头 Chrome
（Playwright 驱动）里，Node 宿主提供 HTTP API、静态资源托管与 ffmpeg 编码。无需桌面环境、
无需 Xorg/Xvfb，Linux 服务器 + NVIDIA 驱动即可获得硬件加速渲染与 NVENC 编码。

## 架构

```
Node 20 宿主（单进程 + N 个无头浏览器渲染工作进程）
├─ :9881  VideoApiServer      视频导出 API（端点与旧版完全一致）
├─ :9881  静态托管             / 渲染页面 · /resources/builtin/* · /apifile/*
├─ :9881  桥接层 /bridge/*     invoke · 二进制写盘 · TTS/翻译代理 · WebSocket
├─ :9882  TTSServiceServer     GPT-SoVITS 代理 / 角色声音管理 / 合成缓存
└─ RenderPool                  N 个无头 Chrome 页面（每页独立 WebGL 上下文）
```

导出数据流（与旧版语义一致）：
`POST /api/v1/export` → 队列（≤2 并发）→ 渲染页面 MediaRecorder 录 WebM（分块回传写盘）
→ Web Audio 混音 WAV → ffmpeg 转码/合流 MP4 → `downloadUrl` 供下载。
AstrBot 插件（`astrbot_plugin_msst/`）**零改动兼容**。

## 依赖

| 组件 | 说明 |
| --- | --- |
| Node.js ≥ 20 | 推荐 22 LTS |
| Chrome / Edge / Chromium | 渲染工作进程。自动按 `MSS_BROWSER_CHANNELS` 顺序探测（默认 msedge → chrome → chromium），Linux 服务器若无系统浏览器会自动回退到 playwright 自带 Chromium |
| ffmpeg | 编码器。优先 `MSS_FFMPEG_PATH`，其次 npm 包 `ffmpeg-static`（安装时自动下载），最后 PATH |
| NVIDIA 驱动（服务器） | `nvidia-smi` 可用即可，**不需要 Xorg / Xvfb / 桌面环境** |

## 构建与启动

```bash
git clone <repo> && cd MySekaiStoryteller
npm ci
npm run build        # typecheck + vite(webrenderer) + tsc(host)
npm start            # node out-host/host/main.js
```

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
npm run e2e                        # 内置示例故事导出 + ffprobe 断言
node scripts/test-parallel.mjs 2   # 双任务并发导出验证
```

E2E 会自动把示例故事中缺失的模型变体替换为本机实际存在的资源。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MSS_PORT` | `9881` | API / 静态 / 桥接层共用端口 |
| `MSS_TTS_PORT` | `9882` | TTS 代理服务端口 |
| `MSS_HOST` | `0.0.0.0` | 监听地址 |
| `MSS_OUTPUT_DIR` | `apifile` | 视频/故事输出目录 |
| `MSS_RESOURCE_DIR` | `resources/builtin` | 内置模型/背景/语音目录 |
| `MSS_CONFIG_DIR` | `user-configs-runtime` | 运行时可写配置目录（save-config 写这里；load 优先读它，再回退 `user-configs/` 内置默认） |
| `MSS_WORKERS` | `1` | 渲染工作进程数（= 并行导出上限，按显存与内存调整，每 worker 约 300-500MB） |
| `MSS_WORKER_RECYCLE_EXPORTS` | `5` | 每个页面完成 N 次导出后回收重建（防 Live2D 内存累积，0 = 不回收） |
| `MSS_FFMPEG_ENCODER` | `auto` | `auto`（探测 nvenc→amf→qsv，全无则 libx264）· `nvenc` · `amd` · `intel` · `libx264`；硬件编码器初始化失败自动回退 CPU |
| `MSS_FFMPEG_PATH` | 自动 | 显式指定 ffmpeg 可执行文件 |
| `MSS_BROWSER_CHANNELS` | `msedge,chrome,chromium` | 浏览器探测顺序（依次回退到 playwright 自带） |
| `MSS_BROWSER_EXECUTABLE` | - | 显式指定浏览器可执行文件（优先于 channel） |
| `MSS_CHROME_ARGS` | - | 附加 Chrome 启动参数（空格分隔） |
| `MSS_LINUX_GPU_ANGLE` | `1` | Linux 上是否追加 `--use-angle=gl`（NVIDIA 硬件 WebGL 关键参数） |
| `MSS_LOG_LEVEL` | `info` | silly/trace/debug/info/warn/error/fatal |

## systemd 部署（Linux 裸机 + NVIDIA）

`deploy/mysekai-host.service`：

```ini
[Unit]
Description=MySekaiStoryteller Pure-API Render Host
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/opt/MySekaiStoryteller
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

若 health 显示 SwiftShader，按顺序尝试：

```bash
MSS_CHROME_ARGS="--use-angle=gl --use-gl=angle"        # 方案 A（Linux NVIDIA 常用）
MSS_CHROME_ARGS="--use-angle=vulkan"                    # 方案 B（较新驱动）
MSS_LINUX_GPU_ANGLE=0 MSS_CHROME_ARGS="--use-angle=swiftshader"  # 确认症状用
```

## 安全提示

API 监听 `0.0.0.0` 且无鉴权（仅 10 次/分钟 IP 限流）。内网使用即可；公网暴露请前置
反向代理（nginx/caddy）加鉴权，并关闭 `/bridge`、`/apifile` 的外部访问。
