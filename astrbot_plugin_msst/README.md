# MySekaiStoryteller AstrBot 插件

QQ/Telegram 机器人的 AI 剧本生成与视频发送插件：接收用户消息 → 调用 LLM 生成符合规范的
JSON 剧本 → 交给 [MySekaiStoryteller 渲染宿主](https://github.com/yonglanws/MySekaiStoryteller)
渲染成 Live2D 视频 → 自动回传到群里。

角色内容为 Project SEKAI「25时，Nightcord见。」同人设定（晓山瑞希 / 东云绘名 / 宵崎奏 / 朝比奈真冬）。

## 功能特性

- **两种创作模式**
  - `/视频对话`：与瑞希单人对话，生成短视频回复（带 30 分钟持久化聊天历史与 roleplay 人设）
  - `/剧本生成`：根据场景描述生成多角色完整剧本，渲染为完整视频
- **结构化输出保障**：优先走 OpenAI 兼容 `json_object` 响应格式；JSON 提取失败或校验失败时，
  把错误信息拼回 prompt 让 AI 自我修正（最多重试 2 次）
- **资源白名单校验**：LLM 输出的模型路径、动作（motion）、表情（facial）逐项校验——
  非法值自动回退该角色默认值，杜绝渲染报错（校验库 `motions.py` 由内置 Live2D 模型自动生成）
- **队列与公平调度**：任务入队排队（容量 20），聊天任务优先于剧本任务；同一用户每轮只执行
  一个任务，防止刷屏；超时（默认 600s）自动取消，失败自动重试（最多 2 次）
- **健壮的视频回传**：本地文件直发 → 多变体 URL → AstrBot 文件服务 token 等五重降级策略，
  兼容 Docker/NAT 等复杂网络环境
- **运维能力**：导出统计、队列查看、任务取消、临时文件自动清理（每 30 分钟清理 2 小时前的产物）、
  维护模式开关

## 系统要求

- AstrBot v3.4.15+
- Python 3.10+
- 已在 AstrBot WebUI 配置好的 LLM 对话模型（无需单独的 API Key）
- 可访问的 MySekaiStoryteller 渲染宿主（本仓库 `npm run build && npm start`）

## 安装步骤

```bash
# 1. 复制插件到 AstrBot
cp -r astrbot_plugin_msst AstrBot/data/plugins/MySekaiStoryteller

# 2. 安装依赖（仅 httpx）
cd AstrBot/data/plugins/MySekaiStoryteller
pip install -r requirements.txt

# 3. 在 AstrBot WebUI 的插件管理中点击"重载插件"
```

## 配置项

在 AstrBot WebUI 的插件配置页修改：

| 配置项                    | 说明                                      | 默认值                   |
| ---------------------- | --------------------------------------- | --------------------- |
| `llm_provider_id`      | 用于生成剧本的 LLM 提供商（留空用当前默认提供商）             | 空                     |
| `mss_api_url`          | 渲染宿主 API 地址（同机 `127.0.0.1:9881`，跨机填对方 IP） | `http://127.0.0.1:9881` |
| `export_timeout`       | 视频导出超时（秒）                               | `600`                 |
| `max_concurrent_exports` | 最大并发导出数                                | `1`                   |
| `temp_dir`             | 临时文件目录（视频/剧本产物，留空用插件数据目录）                | 空                     |
| `callback_api_base`    | AstrBot 文件服务的外部可达地址（`http://<外部IP>:<端口>`），用于视频回传；留空自动探测 | 空 |
| `test_mode`            | 维护模式：正式指令提示维护中，仅 `/测试*` 指令可用              | `false`               |

> **提示词**：剧本生成与对话的 prompt 内置于 `main.py`（含角色人设、模型对照表、开场序列规范、
> 可用动作/表情清单），无需外部模板文件。

## 指令一览

### 创作指令

| 指令              | 别名                                     | 说明                              | 示例                       |
| --------------- | -------------------------------------- | ------------------------------- | ------------------------ |
| `/视频对话 <消息>`     | `/视频生成` `/视频聊天`                        | 与瑞希对话，生成短视频回复                   | `/视频对话 你好`                |
| `/剧本生成 <场景>`     | `/剧本对话` `/故事生成` `/生成剧本` `/生成故事` `/story` | 生成完整剧本视频                       | `/剧本生成 深夜在Nightcord`      |
| `/测试视频对话 <消息>`   | `/测试视频生成` `/测试视频聊天`                     | 同视频对话（不受维护模式限制）                 | `/测试视频对话 你好`              |
| `/测试剧本生成 <场景>`   | `/测试故事生成` `/测试生成剧本` `/测试story`          | 同剧本生成（不受维护模式限制）                 | `/测试剧本生成 放学后的教室`          |
| `/统计`           | `/stats` `/统计信息` `/导出统计`                | 查看导出统计                          | `/统计`                     |

### 管理指令（`/mssadmin` 组）

| 指令                          | 别名              | 说明          | 示例                            |
| --------------------------- | --------------- | ----------- | ----------------------------- |
| `/mssadmin status`          | `/状态` `/系统状态`    | 插件与 API 连接状态 | `/mssadmin status`            |
| `/mssadmin queue`           | `/队列` `/排队`      | 查看队列详情       | `/mssadmin queue`             |
| `/mssadmin cancel <任务ID>`   | `/取消` `/终止` `/停止` | 取消排队中的任务     | `/mssadmin cancel 123`        |
| `/mssadmin cleanup`         | `/清理` `/清理文件`    | 清理临时文件       | `/mssadmin cleanup`           |
| `/mssadmin setapi <URL>`    | -               | 设置渲染宿主 API 地址 | `/mssadmin setapi http://...` |

## 工作流程

```
用户发送 /剧本生成 <场景>
    ↓
前置检查（LLM 提供商 + 渲染宿主健康检查）
    ↓
任务入队（聊天优先于剧本，同用户公平调度）→ 立即回复排队位置与预计等待
    ↓
后台 worker：LLM 生成 JSON 剧本 → 提取/校验/自动修复 → 补译 TTS 文本
    ↓
POST /api/v1/export → 渲染宿主渲染 Live2D 并导出 MP4
    ↓
下载视频（>2MB 时自动 ffmpeg 压缩到 720p）
    ↓
五重降级发送到群（本地文件 → URL → 文件服务 token → …）
    ↓
回执：耗时 / 时长 / 大小；统计入库；临时文件定期清理
```

## 故障排除

### LLM 调用失败

1. 确认 AstrBot WebUI 已配置对话模型提供商
2. `/mssadmin status` 查看 LLM 提供商状态
3. 检查 AstrBot 日志中的详细错误

### 视频导出失败

1. 确认渲染宿主正在运行：`curl http://<宿主IP>:9881/api/v1/health`
2. `/mssadmin status` 确认 MSS API 连接状态
3. 跨设备时检查防火墙放行 9881 端口、`mss_api_url` 填写正确 IP
4. 超时类失败可调大 `export_timeout`，或检查渲染宿主 GPU 状态（health 的 `renderPool`）

### 视频发送失败

1. 配置 `callback_api_base` 为外部可达地址（Docker 部署 AstrBot 时常见）
2. 确认 AstrBot WebUI 的文件服务端口从机器人侧可达
3. 查看宿主日志中五种发送策略的逐级尝试记录

## 项目结构

```
astrbot_plugin_msst/
├── main.py              # 插件主文件（指令、LLM 编排、发送策略、统计与清理）
├── queue_manager.py     # 队列管理（并发控制、公平调度、超时重试）
├── motions.py           # Live2D 动作/表情校验库（由内置模型自动生成，勿手改）
├── metadata.yaml        # 插件元数据
├── _conf_schema.json    # 配置模式定义
├── requirements.txt     # Python 依赖（httpx）
└── README.md            # 本文档
```

## 许可证

本项目与 MySekaiStoryteller 渲染宿主一同以
[GNU GPL v3](https://github.com/yonglanws/MySekaiStoryteller/blob/main/LICENSE) 许可证开源。
