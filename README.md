<!--suppress HtmlDeprecatedAttribute -->

<div align="center" style="text-align: center; margin-top: 10px;">
 <img src="documents/assets/logo.png" style="align-self: center; width: 150px; margin-bottom: 0;" alt="Logo" />
 <h3 style="margin-top: 0; text-align: center;">MySekaiStoryteller-API</h3>
 <p style="text-align: center;">无头纯 API 的 Project SEKAI 风格 Live2D 视频渲染框架</p>
 <div style="display: flex; justify-content: center;">
  <img src="documents/assets/live2d-badge.svg" alt="Live2D Badge" style="margin-top: 0; margin-right: 5px;"/>
  <img src="https://img.shields.io/badge/typescript-20B2AA?logoColor=ffffff&style=for-the-badge&logo=typescript" alt="TypeScript" style="margin-top: 0; margin-right: 5px;" />
  <img src="https://img.shields.io/badge/node-20B2AA?style=for-the-badge&logoColor=white&logo=nodedotjs" alt="Node.js" style="margin-top: 0; margin-right: 5px;" />
  <img src="https://img.shields.io/badge/playwright-20B2AA?style=for-the-badge&logoColor=white&logo=playwright" alt="Playwright" style="margin-top: 0; margin-right: 5px;" />
  <img src="https://img.shields.io/badge/ffmpeg-20B2AA?style=for-the-badge&logoColor=white&logo=ffmpeg" alt="FFmpeg" style="margin-top: 0; margin-right: 5px;" />
  <img src="https://img.shields.io/badge/license-GPL--3.0-20B2AA?style=for-the-badge" alt="GPL 3.0" style="margin-top: 0;" />
 </div>
 <p>
  <a href="#项目简介">项目简介</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#astrbot-插件">AstrBot 插件</a> ·
  <a href="#api-接口">API 接口</a> ·
  <a href="#故事文件格式">故事文件格式</a> ·
  <a href="#资源导入指南">资源导入</a> ·
  <a href="#tts--bgm-配置">TTS / BGM</a> ·
  <a href="#项目结构">项目结构</a> ·
  <a href="#故障排除">故障排除</a>
 </p>
</div>

> [!IMPORTANT]
> 本项目基于 [Untitled-Story/MySekaiStoryteller](https://github.com/Untitled-Story/MySekaiStoryteller) **二次开发**，
> 将其从 **Electron 桌面应用**重构为**无头纯 API 渲染框架**。
> 如需桌面阅读器，请访问原项目。感谢原作者 [GuangChen2333](https://github.com/GuangChen2333) 与
> [Untitled-Story](https://github.com/Untitled-Story) 组织。

> [!CAUTION]
> **本项目目前处于初期开发阶段** —— 接口、配置项与故事格式均可能随时变动，
> **不保证大部分功能的可用性与稳定性**。当前仅核心导出链路在有限环境下验证通过，Linux + NVIDIA 生产环境尚待实测。
> 使用中遇到问题欢迎提交 [Issue](https://github.com/yonglanws/MySekaiStoryteller-API/issues)。

## 项目简介

接收 `*.sekai-story.json` 故事剧本，用 Live2D（Project SEKAI 风格）渲染并导出为 MP4 视频，
通过 HTTP API 对外提供服务。典型用法：部署在一台带 GPU 的服务器上，配合
[AstrBot 插件](astrbot_plugin_msst/) 实现 QQ/Telegram 机器人的 AI 剧本生成与视频自动发送。

| 特性     | 说明                                                                       |
| -------- | -------------------------------------------------------------------------- |
| 渲染引擎 | PixiJS + Live2D 跑在无头 Chrome 里（Playwright 渲染池，每页独立 WebGL 上下文） |
| 视频编码 | ffmpeg 自动探测 NVENC / AMF / QSV 硬件编码，失败自动回退 CPU                 |
| 音频     | 内置 BGM + GPT-SoVITS 语音合成（无 TTS 时自动跳过配音，导出不受影响）        |
| 队列管理 | 任务排队、并发导出、IP 限流、过期文件自动清理                                |
| 统一配置 | 单个 `config.yaml`，全字段中文注释，`MSS_*` 环境变量可覆盖                   |

## 快速开始

```bash
git clone https://github.com/yonglanws/MySekaiStoryteller-API.git
cd MySekaiStoryteller-API

# 1. 安装依赖（ffmpeg 无需手动装，npm 包 ffmpeg-static 会自动带上）
npm ci

# 2. 无 Edge/Chrome 的机器需要装一个浏览器（Windows 一般自带 Edge，可跳过）
npx playwright install chromium

# 3. 生成配置文件（每项都有中文注释，按需修改）
cp config.example.yaml config.yaml

# 4. 准备渲染资源（仓库不附带，见下文「资源准备」）

# 5. 构建（类型检查 + webrenderer + 宿主）
npm run build

# 6. 启动
npm start
```

**启动验证**

```bash
curl http://127.0.0.1:9881/api/v1/health
# renderPool.webglRenderers 应显示真实 GPU（如 NVIDIA / Intel），而非 SwiftShader
```

**全链路验证**（需先完成资源准备）

```bash
npm run e2e                        # 示例故事导出 + 产物断言（编码/分辨率/时长/音轨）
node scripts/test-parallel.mjs 2   # 并发导出验证
```

### 资源准备（必需）

**本仓库不附带渲染资源**（Live2D 模型、背景图、语音、BGM、示例剧本）——为控制仓库体积并
遵循素材版权要求，仓库只保留目录结构，资源需自行放入（详见
[resources/README.md](resources/README.md)）：

```
resources/
├─ models/       Live2D 模型包（<角色>/<变体>/，含 model3.json；根下 models.yaml 为登记表）
├─ images/       背景图 / 卡面
├─ voices/       故事语音（.wav，故事 JSON 按文件名引用）
├─ audio/bgm/    BGM
└─ stories/      *.sekai-story.json 剧本
```

```bash
# 方式一：从上游仓库整体拷贝 resources/（模型/背景/剧本/BGM 齐全，按需取舍）
git clone --depth 1 https://github.com/Untitled-Story/MySekaiStoryteller /tmp/upstream
cp -r /tmp/upstream/resources/. resources/

# 方式二：使用你已有的资源包，按上面的目录结构放入
```

资源根不强制叫 `resources/`：可在 `config.yaml` 的 `paths.resources` 或环境变量
`MSS_RESOURCE_DIR` 指向任意目录。

### Linux 服务器部署（NVIDIA 硬件加速）

详见 **[docs/host-deployment.md](docs/host-deployment.md)**：裸机依赖、资源准备、配置说明、
systemd 单元、NVENC 验证三步与无 GPU 时的参数调优。

## AstrBot 插件

QQ/Telegram 机器人上的 AI 剧本生成与视频发送插件（与渲染宿主通过 HTTP API 交互，零配置兼容）。

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

| 指令                 | 别名                                     | 说明                 | 示例                  |
| -------------------- | ---------------------------------------- | -------------------- | --------------------- |
| `/视频对话 <消息>`   | `/视频生成` `/视频聊天`                  | 与瑞希对话，生成短视频回复 | `/视频对话 你好`      |
| `/剧本生成 <场景>`   | `/剧本对话` `/故事生成` `/生成剧本` `/生成故事` `/story` | 生成完整剧本视频 | `/剧本生成 深夜在Nightcord` |
| `/测试视频对话` `/测试剧本生成` | 见[插件文档](astrbot_plugin_msst/README.md) | 维护模式下仅测试指令可用 | `/测试剧本生成 放学后的教室` |
| `/统计`              | `/stats` `/统计信息` `/导出统计`         | 查看视频导出统计     | `/统计`               |

管理指令使用 `/mssadmin` 指令组（均带中文别名）：

| 指令                        | 说明           |
| --------------------------- | -------------- |
| `/mssadmin status`          | 插件与 API 连接状态 |
| `/mssadmin queue`           | 查看队列详情   |
| `/mssadmin cancel <任务ID>` | 取消排队中的任务 |
| `/mssadmin cleanup`         | 清理临时文件   |
| `/mssadmin setapi <URL>`    | 设置渲染宿主 API 地址 |

> **提示**：完整指令别名、配置说明与故障排除见[插件文档](astrbot_plugin_msst/README.md)。

**插件配置项（AstrBot WebUI）：**

| 配置项                     | 说明                        | 默认值                  |
| -------------------------- | --------------------------- | ----------------------- |
| `llm_provider_id`          | 用于生成剧本的 LLM 提供商   | 留空使用当前默认        |
| `mss_api_url`              | MySekaiStoryteller-API 渲染宿主地址 | `http://127.0.0.1:9881` |
| `export_timeout`           | 视频导出超时时间（秒）      | `600`                   |
| `max_concurrent_exports`   | 最大并发导出数              | `1`                     |
| `temp_dir`                 | 临时文件存储目录            | 空（用插件数据目录）    |
| `callback_api_base`        | AstrBot 文件服务外部可达地址（视频回传用） | 空（自动探测） |
| `test_mode`                | 维护模式（仅测试指令可用）  | `false`                 |

## API 接口

渲染宿主启动后提供 HTTP API（默认 `http://0.0.0.0:9881`）：

| 端点                             | 方法 | 说明                 |
| -------------------------------- | ---- | -------------------- |
| `/api/v1/export`                 | POST | 提交故事导出视频     |
| `/api/v1/export/:taskId/status`  | GET  | 查询任务状态         |
| `/api/v1/export/:taskId/cancel`  | POST | 取消任务             |
| `/api/v1/download/:filename`     | GET  | 下载导出的视频       |
| `/api/v1/files`                  | GET  | 分页列出导出文件     |
| `/api/v1/cleanup`                | POST | 触发过期文件清理     |
| `/api/v1/health`                 | GET  | 健康检查（含渲染池/GPU 状态） |
| `/api/v1/status`                 | GET  | 队列状态             |

提交导出只需把完整故事 JSON 作为请求体：

```bash
curl -X POST http://127.0.0.1:9881/api/v1/export \
  -H "Content-Type: application/json" \
  -d @resources/stories/multi-character-demo.sekai-story.json
```

宿主会自动把请求留档一份到 `apifile/`，便于排查。

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

- 故事内的 `model` / `image` 路径相对于**资源根** `resources/`（即 `resources/models/...`、
  `resources/images/...`），宿主通过 `/resources/*` 提供访问
- 指令片段（`snippets`）的完整类型定义见 `src/common/types/Story.ts`，
  也可参考随资源包提供的示例剧本

## 资源导入指南

### 新增 Live2D 角色（模型）

1. 把模型包整个拷到 `resources/models/<角色>/<变体>/`，目录内需含 `model3.json`
   （动作 `motions/*.motion3.json` 是模型包的一部分，由 model3.json 的
   `FileReferences.Motions` 索引——**动作文件跟着模型走，不需要单独登记**）
2. 在 `resources/models/models.yaml` 登记一行（`id` 全表唯一、`name` 角色全名、
   `shortName` 简称、`path` 以磁盘实际文件名为准）
3. 完成。宿主 30 秒内自动识别；AstrBot 插件 5 分钟内自动感知（可发 `/mssadmin resources` 确认），
   提示词中的角色对照表、动作/表情清单、校验白名单**全部自动更新，无需改任何代码**

> 插件端为「晓山瑞希/东云绘名/宵崎奏/朝比奈真冬」内置了详细人设档案；
> 新角色会生成通用档案条目由 LLM 依据角色名演绎。如需为新角色定制 TTS 音色，
> 在宿主 `config.yaml` 的 `tts.characters` 节配置。

### 背景图 / 语音 / BGM

| 资源   | 存放位置               | 如何生效                                                    |
| ------ | ---------------------- | ----------------------------------------------------------- |
| 背景图 | `resources/images/`    | 自动进入目录，插件提示词与校验即时可用                      |
| 故事语音 | `resources/voices/`  | 故事 JSON 的 `voice` 字段按文件名引用                       |
| BGM    | `resources/audio/bgm/` | 在宿主 `config.yaml` 的 `bgm.path` 指定（如 `audio/bgm/bg1.mp3`） |

## TTS / BGM 配置

全部在 `config.yaml` 中完成（见 `config.example.yaml` 的 `tts:` / `bgm:` 节）：

1. 启动 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)（默认端口 `9880`），
   把地址填入 `tts.apiBaseUrl`
2. 在 `tts.characters` 下为每个角色配置参考音频（`refAudioPath` 为 **GPT-SoVITS 服务端**可访问的路径）
   与提示文本
3. BGM 放在 `resources/audio/bgm/` 下，`bgm.path` 填相对资源根的路径（如 `audio/bgm/bg1.mp3`）
4. `tts.enabled: false` 可整体关闭配音；无 TTS 时导出仍会成功，只是没有角色配音

## 项目结构

```
config.example.yaml   统一配置样例（复制为 config.yaml 使用，config.yaml 不入库）
src/host/             Node 宿主：API 服务 / 静态托管 / 桥接层 / 渲染池 / ffmpeg 编码
src/webrender/        渲染工作进程页面（无头浏览器加载，构建产物在 out/webrenderer/）
src/renderer/         渲染引擎（PixiJS + Live2D + 导出管线）
src/common/           宿主与渲染侧共享的故事类型定义（Story.ts）
src/shared/           宿主与渲染侧共享的 ffmpeg 模块
resources/            资源根：models/ images/ voices/ audio/bgm/ stories/（不入库，见 resources/README.md）
astrbot_plugin_msst/  AstrBot 机器人插件
out-host/             宿主编译产物（npm run build:host 生成）
docs/                 部署文档；deploy/ systemd 单元；scripts/ 测试与工具脚本
```

## 故障排除

**Q: 启动报 "Failed to launch any browser"**

系统没有 Edge/Chrome 且未下载 playwright 浏览器。执行 `npx playwright install chromium`
或安装系统 Chrome/Edge。

**Q: health 里 WebGL renderer 显示 SwiftShader / llvmpipe**

WebGL 落到了软件渲染，导出会慢 5-10 倍，并且可能会遇到音画不同步等问题。
Linux + NVIDIA 下尝试 `MSS_CHROME_ARGS="--use-angle=gl"`，详见部署文档的参数调优章节。

**Q: 视频导出失败或卡住**

- 查看宿主日志中的 ffmpeg / 渲染错误
- 尝试降低 `render.workers`（显存/内存不足时）
- 确认 `video.encoder` 对应的硬件在当前机器可用（失败会自动回退 CPU）

**Q: AstrBot 插件无法连接**

- 确认 `mss_api_url` 配置正确
- `curl http://<服务器>:9881/api/v1/health` 确认宿主存活

## 许可证

本项目基于 [Untitled-Story/MySekaiStoryteller](https://github.com/Untitled-Story/MySekaiStoryteller)
二次开发，沿用 **[GNU GPL v3](LICENSE)** 许可证开源；导出视频的使用另受原项目中的
[VIDEO-LICENSE-CN.md](VIDEO-LICENSE-CN.md) 约束。

## 致谢

- [Untitled-Story/MySekaiStoryteller](https://github.com/Untitled-Story/MySekaiStoryteller)
- [Sekai-World/sekai-viewer](https://github.com/Sekai-World/sekai-viewer)
- [lezzthanthree/SEKAI-Stories](https://github.com/lezzthanthree/SEKAI-Stories)
