# MySekaiStoryteller Astrbot 插件

基于 AI 的 JSON 剧本生成与视频渲染插件，集成 MySekaiStoryteller API，实现从场景描述到视频的端到端自动化流程。

## 功能特性

- **AI 剧本生成**: 使用 Astrbot 已配置的 LLM 模型生成符合规范的 JSON 剧本
- **视频导出**: 调用 MySekaiStoryteller API 将 JSON 剧本渲染为视频
- **一键完成**: `/mss <场景描述>` 即可自动完成"生成剧本 + 导出视频"全流程
- **智能 JSON 提取**: 自动从 AI 响应中提取和验证 JSON 内容
- **跨设备支持**: API 服务器绑定到 `0.0.0.0`，支持局域网内其他设备访问
- **并发控制**: 支持配置最大并发导出任务数
- **状态查询**: 实时查看插件和 API 连接状态

## 系统要求

- Astrbot v3.4.15+
- Python 3.10+
- 已配置的 LLM 对话模型（在 Astrbot WebUI 中配置）
- 运行中的 MySekaiStoryteller 实例（视频导出服务）

## 安装步骤

### 1. 克隆插件

```bash
cd AstrBot/data/plugins
git clone <插件仓库地址> MySekaiStoryteller
```

### 2. 安装依赖

```bash
cd MySekaiStoryteller
pip install -r requirements.txt
```

### 3. 配置插件

在 Astrbot WebUI 中找到 **MySekaiStoryteller** 插件，点击 **管理** 进入配置页面：

| 配置项                   | 说明                        | 默认值                  |
| ------------------------ | --------------------------- | ----------------------- |
| `mss_api_url`            | MySekaiStoryteller API 地址 | `http://127.0.0.1:9881` |
| `export_timeout`         | 视频导出超时时间（秒）      | `600`                   |
| `max_concurrent_exports` | 最大并发导出数              | `1`                     |
| `temp_dir`               | 临时文件存储目录            | 空                      |
| `prompt_template_path`   | 提示模板文件路径            | `promot.md`             |

> **注意**：LLM 模型直接使用 Astrbot 已配置的对话模型，无需单独配置 API Key。

### 4. 跨设备访问配置

如果 Astrbot 和 MySekaiStoryteller 运行在不同设备上：

1. 确保两台设备在同一局域网内
2. MySekaiStoryteller 的 API 已绑定到 `0.0.0.0`（默认已配置）
3. 在插件配置中将 `mss_api_url` 改为 MySekaiStoryteller 设备的 IP 地址，例如：`http://192.168.1.100:9881`
4. 如果启用了 Windows 防火墙，需要放行 9881 端口的入站连接

### 5. 重载插件

在 Astrbot WebUI 的插件管理中点击 **重载插件**。

## 使用指南

### 主要指令

#### `/mss <场景描述>`

生成剧本并导出视频（一步完成）。

**示例：**

```
/mss 深夜在Nightcord频道，看到队友发了一句今天好累
/mss 晓山瑞希在房间里做手工，突然想到一个有趣的点子
```

**响应流程：**

```
正在生成剧本并导出视频...
场景: 深夜在Nightcord频道...
剧本生成成功，正在导出视频...
视频导出成功！
总耗时: 120秒
时长: 15000ms
大小: 5.2 MB
[视频文件]
```

### 管理指令

#### `/mssadmin status`

查看插件和 API 连接状态。

**响应示例：**

```
MySekaiStoryteller 插件状态:

🤖 LLM 提供商: openai (openai)
🖥️ MSS API: ✅ 正常
📡 MSS 地址: http://192.168.1.100:9881
⚙️ 活跃导出: 0/1
📁 临时目录: data/plugins/MySekaiStoryteller/videos
📝 提示词模板: ✅ 已加载

使用方法: /mss <场景描述>
```

#### `/mssadmin setapi <地址>`

设置 MSS API 地址。

**示例：**

```
/mssadmin setapi http://192.168.1.100:9881
```

#### `/mssadmin cleanup`

清理临时存储的视频和剧本文件。

## 工作流程

```
用户输入: /mss <场景描述>
         ↓
调用 Astrbot 已配置的 LLM 生成剧本
         ↓
自动提取和验证 JSON
         ↓
调用 MSS API /api/v1/export 导出视频
         ↓
通过 Comp.Video.fromFileSystem() 发送视频给用户
```

## 故障排除

### LLM 调用失败

1. 确认在 Astrbot WebUI 中已配置对话模型提供商
2. 使用 `/mssadmin status` 查看 LLM 提供商状态
3. 检查 Astrbot 日志中的详细错误信息

### 视频导出失败

1. 确保 MySekaiStoryteller 正在运行
2. 使用 `/mssadmin status` 确认 MSS API 连接状态
3. 如果是跨设备访问，检查防火墙和 IP 地址是否正确
4. 确认剧本文件格式正确

### 跨设备连接失败

1. 确认两台设备在同一局域网
2. 检查 MySekaiStoryteller 是否绑定到 `0.0.0.0`（查看启动日志）
3. 使用 `/mssadmin setapi` 设置正确的 IP 地址
4. 在 MySekaiStoryteller 所在设备上测试：`http://<IP>:9881/api/v1/health`
5. 检查 Windows 防火墙是否放行了 9881 端口

## API 参考

### MySekaiStoryteller API

| 端点                          | 方法 | 用途     |
| ----------------------------- | ---- | -------- |
| `/api/v1/health`              | GET  | 健康检查 |
| `/api/v1/export`              | POST | 视频导出 |
| `/api/v1/download/<filename>` | GET  | 文件下载 |

## 项目结构

```
astrbot/
├── main.py              # 插件主文件
├── metadata.yaml        # 插件元数据
├── _conf_schema.json    # 配置模式定义
├── requirements.txt     # Python 依赖
└── README.md            # 本文档
```

## 许可证

与 MySekaiStoryteller 相同的许可证。
