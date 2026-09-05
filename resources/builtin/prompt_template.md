## 剧本格式要求

输出必须符合以下JSON格式：

```json
{
  "$schema": "https://raw.githubusercontent.com/Untitled-Story/MySekaiStoryteller/refs/heads/master/sekai-story.schema.json",
  "models": [
    {
      "id": 1,
      "model": "20mizuki/20mizuki_normal/20mizuki_normal.model3.json",
      "normal_scale": 2.1,
      "small_scale": 1.8,
      "anchor": 0.5
    }
  ],
  "images": [
    {
      "id": 1,
      "image": "bg_e000401.jpg"
    }
  ],
  "snippets": [
    // 剧本内容
  ]
}
```

## 可用动作列表（Motion）

### 普通动作（w-normal-）

- `w-normal-greeting01` - 打招呼
- `w-normal-tilthead01/02/03/04` - 歪头思考
- `w-normal-nod01` - 点头
- `w-normal-shake01/02` - 摇头
- `w-normal-sigh01` - 叹气
- `w-default01` - 默认姿势
- `w-normal-relax01` - 放松
- `w-normal-lookaway01` - 看向别处

### 开心动作（w-happy-）

- `w-happy-jump01` - 开心跳跃
- `w-happy-forward01` - 开心前倾
- `w-happy-clap01` - 拍手
- `w-happy-shakehand01` - 挥手
- `w-happy-wink02` - 眨眼
- `w-happy-nod01` - 开心点头

### 可爱动作（w-cute-）

- `w-cute-nod01` - 可爱点头
- `w-cute-tilthead03/07/08` - 可爱歪头
- `w-cute-glad01/02` - 开心
- `w-cute-smug01` - 得意
- `w-cute-wink01` - 眨眼
- `w-cute-sad01` - 悲伤
- `w-cute-relief01` - 释然
- `w-cute-surprise01` - 惊讶
- `w-cute-posetilthead07` - 姿势歪头

### 成熟动作（w-adult-）

- `w-adult-laugh01` - 成熟大笑
- `w-adult-think01` - 成熟思考

### 酷动作（w-cool-）

- `w-cool-tilthead01` - 酷酷歪头

## 可用表情列表（Facial）

- `face_smile_01/02/03/04/05/06/07` - 各种微笑
- `face_think_01` - 思考
- `face_normal_01` - 普通
- `face_trouble_01` - 困扰
- `face_sad_01/02` - 悲伤
- `face_shy_01` - 害羞
- `face_surprise_01` - 惊讶
- `face_serious_01` - 认真
- `face_sparkling_01` - 闪闪发光

## 剧本结构要求

### 1. 开场序列

```json
[
  { "type": "BlackOut", "duration": 800 },
  { "type": "ChangeBackgroundImage", "imageId": 1 },
  { "type": "BlackIn", "duration": 1000 },
  { "type": "Telop", "content": "场景名称" },
  { "type": "LayoutAppear", "modelId": 1, "motion": "入场动作", "facial": "入场表情" }
]
```

### 2. 对话单元结构

每个对话单元必须包含：

```json
// 1. 开场动作（wait: true）
{
    "type": "Motion",
    "wait": true,
    "delay": 0.1,
    "data": {
        "modelId": 1,
        "motion": "动作名称",
        "facial": "表情名称",
        "facialFirst": false
    }
}

// 2. 开始说话（wait: false）
{
    "type": "Talk",
    "wait": false,
    "delay": 0,
    "data": {
        "speaker": "晓山瑞希",
        "content": "对话内容",
        "modelId": 1,
        "voice": ""
    }
}

// 3. 说话中动作（wait: false，可选，可多个）
{
    "type": "Motion",
    "wait": false,
    "delay": 0.5,
    "data": {
        "modelId": 1,
        "motion": "动作名称",
        "facial": "表情名称",
        "facialFirst": false
    }
}
```

### 3. 退场序列

```json
[
  { "type": "HideTalk", "delay": 0.2 },
  { "type": "LayoutClear", "modelId": 1, "moveSpeed": "Normal" },
  { "type": "BlackOut", "duration": 800 }
]
```

## 动作设计原则

1. **情感匹配**：动作和表情必须与对话内容情感一致
2. **变化丰富**：每个对话使用不同的动作和表情组合
3. **节奏感**：使用 `wait: false` 和 delay 创建动态表演
4. **自然过渡**：长对话中间插入 1-2 个说话中动作
5. **避免重复**：同一动作不要在相邻对话中使用

## 输出要求

1. 生成完整的JSON文件内容
2. 每个对话单元有2-3个动作
3. 对话内容符合角色性格
4. 使用中文输出对话内容
5. 保持JSON格式正确

<br />

根据用户输入生成符合上述格式的完整剧本。
