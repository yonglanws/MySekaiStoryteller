# resources — 渲染资源根

本仓库**不附带**渲染资源（Live2D 模型、背景图、语音、BGM、示例剧本），以控制仓库体积并遵循素材版权要求。请自行将资源放入对应目录：

```
resources/
├─ models/       Live2D 模型包（<角色>/<变体>/，含 model3.json；根下 models.yaml 为登记表）
├─ images/       背景图 / 卡面
├─ voices/       故事语音（.wav，故事 JSON 按文件名引用）
├─ audio/bgm/    BGM
└─ stories/      *.sekai-story.json 剧本
```

获取方式（任选其一）：

1. 从上游仓库 [Untitled-Story/MySekaiStoryteller](https://github.com/Untitled-Story/MySekaiStoryteller) 的 `resources/` 目录拷贝；
2. 使用你已有的资源包，按上面目录结构放入。

资源根不强制叫 `resources/`：可在 `config.yaml` 的 `paths.resources` 或环境变量 `MSS_RESOURCE_DIR` 指向任意目录。新增模型后只需在 `resources/models/models.yaml` 登记一行，宿主会自动识别，详见主 README 的「资源导入指南」。
