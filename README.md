<!--suppress HtmlDeprecatedAttribute -->

<div align="center" style="text-align: center; margin-top: 10px;">
 <img src="documents/assets/logo.png" style="align-self: center; width: 150px; margin-bottom: 0;" alt="Logo" />
 <h3 style="margin-top: 0; text-align: center;">My Sekai Storyteller</h3>
 <p style="text-align: center;">无头纯 API 的 Project SEKAI 风格 Live2D 视频渲染框架</p>
 <div style="display: flex; justify-content: center;">
  <img src="documents/assets/live2d-badge.svg" alt="Live2D Badge" style="margin-top: 0; margin-right: 5px;"/>
  <img src="https://img.shields.io/badge/typescript-20B2AA?logoColor=ffffff&style=for-the-badge&logo=typescript" alt="TypeScript" style="margin-top: 0; margin-right: 5px;" />
  <img src="https://img.shields.io/badge/node-20B2AA?style=for-the-badge&logoColor=white&logo=nodedotjs" alt="Node.js" style="margin-top: 0;" />
  <img src="https://img.shields.io/badge/playwright-20B2AA?style=for-the-badge&logoColor=white&logo=playwright" alt="Playwright" style="margin-top: 0; margin-right: 5px;" />
  <img src="https://img.shields.io/badge/ffmpeg-20B2AA?style=for-the-badge&logoColor=white&logo=ffmpeg" alt="FFmpeg" style="margin-top: 0;" />
 </div>
</div>

**[English](README.md)** | **简体中文 (当前)**

## 项目简介

MySekaiStoryteller 是一个**无头（headless）视频渲染服务**：接收 `*.sekai-story.json`
故事剧本，用 Live2D（Project SEKAI 风格）渲染并导出为 MP4 视频，通过 HTTP API 对外提供
服务。适合部署在无桌面环境的 Linux 服务器（含 NVIDIA GPU 硬件加速），配合
[AstrBot 插件](astrbot_plugin_msst/) 实现 QQ/Telegram 机器人的 AI 剧本生成与视频发送。

- **渲染引擎**: PixiJS + Live2D 跑在无头 Chrome（Playwright 渲染池，每页面独立 WebGL 上下文）
- **视频编码**: ffmpeg（自动探测 NVENC / AMF / QSV 硬件编码，失败自动回退 CPU）
- **音频**: 内置 BGM + TTS 语音合成（GPT-SoVITS 本地服务或远程 TTS 服务）
- **队列管理**: 任务排队、并发导出、限流、过期文件自动清理
- **AI 集成**: AstrBot 插件支持 LLM 生成剧本 → 自动渲染 → 自动发视频

## 快速开始

### 构建与启动

```bash
git clone https://github.com/Untitled-Story/MySekaiStoryteller.git
cd MySekaiStoryteller

npm ci
npm run build      # 类型检查 + webrenderer 构建 + 宿主构建
npm start          # 启动宿主（默认 0.0.0.0:9881 + TTS 9882）
```

启动后验证：

```bash
curl http://127.0.0.1:9881/api/v1/health
# renderPool.webglRenderers 应显示真实 GPU（如 NVIDIA / Intel），而非 SwiftShader
```

### 端到端测试

```bash
npm run e2e                        # 内置示例故事导出 + 产物断言
node scripts/test-parallel.mjs 2   # 并发导出验证
```

### Linux 服务器部署（NVIDIA 硬件加速）

详见 **[docs/host-deployment.md](docs/host-deployment.md)**：裸机依赖、全部环境变量、
systemd 单元、NVENC 验证与无 GPU 时的参数调优。

## AstrBot 插件

本插件提供 QQ 机器人上的 AI 剧本生成和视频发送功能（与渲染宿主通过 HTTP API 交互，零配置兼容）。

**安装步骤：**

```bash
# 1. 复制插件到 AstrBot
cp -r astrbot_plugin_msst AstrBot/data/plugins/MySekaiStoryteller

# 2. 安装依赖
cd AstrBot/data/plugins/MySekaiStoryteller
pip install -r requirements.txt

# 3. 在 AstrBot WebUI 中点击"重载插件"
```

**使用说明：**

| 指令           | 别名                        | 说明            | 示例                   |
| ------------ | ------------------------- | ------------- | -------------------- |
| `/统计`        | `/stats` `/统计信息` `/导出统计`   | 查看视频导出统计     | `/统计`                |
| `/视频对话 <消息>` | `/对话` `/聊天` `/chat` `/视频聊天` | 与瑞希聊天，生成短视频回复 | `/视频对话 你好`           |
| `/剧本生成 <场景>` | `/剧本` `/故事` `/story` `/视频生成` | 生成完整剧本视频      | `/剧本生成 深夜在Nightcord` |
| `/取消任务 <ID>` | `/mssadmin cancel <ID>`   | 取消正在排队的任务     | `/取消任务 123`          |
| `/状态`        | `/mssadmin status`        | 查看系统状态        | `/状态`                |
| `/清理`        | `/mssadmin cleanup`       | 清理临时文件        | `/清理`                |
| `/设置api <URL>` | `/mssadmin setapi <URL>`  | 设置 API 地址     | `/设置api http://...`  |

> **提示**: 更多管理指令请使用 `/mssadmin` 指令组，例如 `/mssadmin queue` 查看队列。

**配置项：**

| 配置项                      | 说明                        | 默认值                     |
| ------------------------ | ------------------------- | ----------------------- |
| `llm_provider_id`        | 用于生成剧本的 LLM 提供商       | 留空使用当前默认           |
| `mss_api_url`            | MySekaiStoryteller API 地址 | `http://127.0.0.1:9881` |
| `export_timeout`         | 视频导出超时时间（秒）               | `600`                   |
| `max_concurrent_exports` | 最大并发导出数                   | `1`                     |
| `test_mode`              | 维护模式（仅测试指令可用）             | `false`                 |

## API 接口

渲染宿主启动后提供 HTTP API（默认 `http://0.0.0.0:9881`）：

| 端点                                | 方法   | 说明        |
| --------------------------------- | ---- | --------- |
| `/api/v1/export`                  | POST | 提交故事导出视频  |
| `/api/v1/export/:taskId/status`   | GET  | 查询任务状态    |
| `/api/v1/export/:taskId/cancel`   | POST | 取消任务      |
| `/api/v1/download/:filename`      | GET  | 下载导出的视频   |
| `/api/v1/files`                   | GET  | 分页列出导出文件  |
| `/api/v1/cleanup`                 | POST | 触发过期文件清理  |
| `/api/v1/health`                  | GET  | 健康检查（含渲染池/GPU 状态） |
| `/api/v1/status`                  | GET  | 队列状态      |

TTS 代理服务（默认 `:9882`）：`/synthesize`、`/synthesize/audio`、`/synthesize/batch`、
`/config`、`/character`、`/characters`、`/health` 等。

## 故事文件格式

故事通过 `*.sekai-story.json` 文件定义，包含 `models`、`images` 和 `snippets` 三个字段：

```json
{
  "models": [
    {"id": 1, "model": "20mizuki/20mizuki_normal/20mizuki_normal.model3.json"}
  ],
  "images": [
    {"id": 1, "image": "bg_e000401.jpg"}
  ],
  "snippets": [
    {"type": "ChangeLayoutMode", "wait": false, "delay": 0, "data": {"mode": 0}},
    {"type": "BlackOut", "wait": true, "delay": 0, "data": {"duration": 500}},
    {"type": "ChangeBackgroundImage", "wait": true, "delay": 0, "data": {"image": {"id": 1}}},
    {"type": "BlackIn", "wait": true, "delay": 0, "data": {"duration": 800}},
    {"type": "LayoutAppear", "wait": true, "delay": 0, "data": {"modelId": 1, "from": {"side": "Right"}}},
    {"type": "Talk", "wait": true, "delay": 0, "data": {"speaker": "晓山瑞希", "content": "你好！"}}
  ]
}
```

模型/背景/语音等资源放在 `resources/builtin/`（宿主通过 `/resources/builtin/*` 提供访问）。
通过 API 导出时直接在请求体中提交完整故事 JSON，无需落盘。

## TTS 配置

### 本地 TTS 服务

项目使用 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) TTS 服务：

1. 启动 GPT-SoVITS（默认端口 `9880`）
2. 通过 `user-configs/mss-tts-config.json`（或 `MSS_CONFIG_DIR` 运行时配置）配置
   角色参考音频与提示文本

### 远程 TTS 服务

宿主内置 TTS 代理服务（默认端口 `9882`）：合成、批量合成、角色声音注册、缓存管理、
自动健康检查。

## 项目结构

```
src/host/        Node 宿主：API 服务 / 桥接层 / 渲染池 / ffmpeg 编码
src/webrender/   渲染工作进程页面（无头浏览器加载）
src/renderer/    渲染引擎（PixiJS + Live2D + 导出管线）
src/shared/      宿主与渲染侧共享的 ffmpeg 模块
resources/       内置 Live2D 模型 / 背景 / 语音 / 示例故事
astrbot_plugin_msst/  AstrBot 机器人插件
```

## 系统要求

| 组件            | 最低要求                   | 推荐配置                        |
| --------------- | ------------------------ | ------------------------------- |
| **操作系统**      | Windows 10 / Linux    | Linux 服务器（无桌面环境）          |
| **CPU / 内存**   | 双核 2.0 GHz / 4 GB     | 四核 2.5 GHz+ / 8 GB+            |
| **GPU**         | 支持 WebGL             | NVIDIA（NVENC）/ Intel（QSV）      |
| **Node.js**     | 20.x                  | 22 LTS                         |
| **浏览器**        | Edge / Chrome / Chromium | 与系统匹配的最新稳定版               |
| **ffmpeg**      | 4.x（含 libx264）      | 6.x+（含 nvenc 等硬件编码器）        |

## 故障排除

**Q: health 里 WebGL renderer 显示 SwiftShader / llvmpipe**

WebGL 落到了软件渲染。Linux + NVIDIA 下尝试 `MSS_CHROME_ARGS="--use-angle=gl"`，
详见部署文档的参数调优章节。

**Q: 视频导出失败或卡住**

- 查看宿主日志中的 ffmpeg / 渲染错误
- 尝试降低 `MSS_WORKERS`（显存/内存不足时）
- 确认 `MSS_FFMPEG_ENCODER` 对应的硬件在当前机器可用（失败会自动回退 CPU）

**Q: TTS 语音合成失败**

- 确认 GPT-SoVITS 已启动（默认 `127.0.0.1:9880`）
- 无 TTS 时导出仍会成功（自动跳过语音），只是没有角色配音

**Q: AstrBot 插件无法连接**

- 确认 `mss_api_url` 配置正确
- `curl http://<服务器>:9881/api/v1/health` 确认宿主存活

## 许可证

本项目采用 [MIT 许可证](LICENSE)；导出视频的使用受 [VIDEO-LICENSE-CN.md](VIDEO-LICENSE-CN.md) 约束。

## 致谢

- [Project SEKAI](https://pjsekai.sega.jp/) - 灵感和资源来源
- [Live2D Cubism](https://www.live2d.com/) - Live2D 渲染引擎
- [Playwright](https://playwright.dev/) - 无头浏览器自动化
- [FFmpeg](https://ffmpeg.org/) - 视频编码和音频处理
