import asyncio
import json
import os
import re
import time
import shutil
import socket
import httpx
from pathlib import Path
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.event import MessageChain
import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig

from .queue_manager import VideoExportQueue, QueueFullError
from .motions import (
    CHARACTER_NAMES, CHARACTER_MOTIONS, CHARACTER_FACIALS,
    ALL_MOTIONS, ALL_FACIALS,
    get_valid_motions, get_valid_facials, get_default_motion, get_default_facial,
)

STORY_JSON_SCHEMA = {
    "type": "object",
    "required": ["models", "images", "snippets"],
    "properties": {
        "models": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "model"],
                "properties": {
                    "id": {"type": "number", "description": "模型唯一ID"},
                    "model": {"type": "string", "description": "模型路径，如 20mizuki/20mizuki_normal/20mizuki_normal.model3.json"},
                    "normal_scale": {"type": "number", "default": 2.1},
                    "small_scale": {"type": "number", "default": 1.8},
                    "anchor": {"type": "number", "default": 0.5}
                }
            }
        },
        "images": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "image"],
                "properties": {
                    "id": {"type": "number", "description": "图片唯一ID"},
                    "image": {"type": "string", "description": "背景图片文件名，如 bg_e000401.jpg"}
                }
            }
        },
        "snippets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "wait", "delay"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "ChangeLayoutMode", "ChangeBackgroundImage", "LayoutAppear",
                            "LayoutClear", "Talk", "HideTalk", "Move", "Motion",
                            "Telop", "BlackOut", "BlackIn", "DoParam"
                        ]
                    },
                    "wait": {"type": "boolean", "description": "是否等待此片段完成"},
                    "delay": {"type": "number", "description": "延迟时间（秒）"}
                }
            }
        }
    }
}

SNIPPET_SCHEMAS = {
    "ChangeLayoutMode": {
        "required": ["type", "wait", "delay", "data"],
        "properties": {
            "type": {"const": "ChangeLayoutMode"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"},
            "data": {
                "type": "object",
                "required": ["mode"],
                "properties": {
                    "mode": {"type": "string", "enum": ["Normal", "Three"]}
                }
            }
        }
    },
    "ChangeBackgroundImage": {
        "required": ["type", "wait", "delay", "data"],
        "properties": {
            "type": {"const": "ChangeBackgroundImage"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"},
            "data": {
                "type": "object",
                "required": ["imageId"],
                "properties": {
                    "imageId": {"type": "number"}
                }
            }
        }
    },
    "LayoutAppear": {
        "required": ["type", "wait", "delay", "data"],
        "properties": {
            "type": {"const": "LayoutAppear"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"},
            "data": {
                "type": "object",
                "required": ["modelId", "from", "to", "motion", "facial", "moveSpeed"],
                "properties": {
                    "modelId": {"type": "number"},
                    "from": {
                        "type": "object",
                        "required": ["side"],
                        "properties": {
                            "side": {"type": "string", "enum": ["Center", "Left", "Right"]},
                            "offset": {"type": "number", "default": 0}
                        }
                    },
                    "to": {
                        "type": "object",
                        "required": ["side"],
                        "properties": {
                            "side": {"type": "string", "enum": ["Center", "Left", "Right"]},
                            "offset": {"type": "number", "default": 0}
                        }
                    },
                    "motion": {"type": "string"},
                    "facial": {"type": "string"},
                    "facialFirst": {"type": "boolean", "default": True},
                    "moveSpeed": {"type": "string", "enum": ["Slow", "Normal", "Fast", "Immediate"]},
                    "hologram": {"type": "boolean", "default": False}
                }
            }
        }
    },
    "LayoutClear": {
        "required": ["type", "wait", "delay", "data"],
        "properties": {
            "type": {"const": "LayoutClear"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"},
            "data": {
                "type": "object",
                "required": ["modelId", "from", "to", "moveSpeed"],
                "properties": {
                    "modelId": {"type": "number"},
                    "from": {
                        "type": "object",
                        "required": ["side"],
                        "properties": {
                            "side": {"type": "string", "enum": ["Center", "Left", "Right"]},
                            "offset": {"type": "number", "default": 0}
                        }
                    },
                    "to": {
                        "type": "object",
                        "required": ["side"],
                        "properties": {
                            "side": {"type": "string", "enum": ["Center", "Left", "Right"]},
                            "offset": {"type": "number", "default": 0}
                        }
                    },
                    "moveSpeed": {"type": "string", "enum": ["Slow", "Normal", "Fast", "Immediate"]}
                }
            }
        }
    },
    "Talk": {
        "required": ["type", "wait", "delay", "data"],
        "properties": {
            "type": {"const": "Talk"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"},
            "data": {
                "type": "object",
                "required": ["speaker", "content"],
                "properties": {
                    "speaker": {"type": "string", "description": "说话者名字"},
                    "content": {"type": "string", "description": "对话内容，禁止换行"},
                    "modelId": {"type": "number", "default": -1},
                    "voice": {"type": "string", "default": ""}
                }
            }
        }
    },
    "HideTalk": {
        "required": ["type", "wait", "delay"],
        "properties": {
            "type": {"const": "HideTalk"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"}
        }
    },
    "Move": {
        "required": ["type", "wait", "delay", "data"],
        "properties": {
            "type": {"const": "Move"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"},
            "data": {
                "type": "object",
                "required": ["modelId", "from", "to", "moveSpeed"],
                "properties": {
                    "modelId": {"type": "number"},
                    "from": {
                        "type": "object",
                        "required": ["side"],
                        "properties": {
                            "side": {"type": "string", "enum": ["Center", "Left", "Right"]},
                            "offset": {"type": "number", "default": 0}
                        }
                    },
                    "to": {
                        "type": "object",
                        "required": ["side"],
                        "properties": {
                            "side": {"type": "string", "enum": ["Center", "Left", "Right"]},
                            "offset": {"type": "number", "default": 0}
                        }
                    },
                    "moveSpeed": {"type": "string", "enum": ["Slow", "Normal", "Fast", "Immediate"]}
                }
            }
        }
    },
    "Motion": {
        "required": ["type", "wait", "delay", "data"],
        "properties": {
            "type": {"const": "Motion"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"},
            "data": {
                "type": "object",
                "required": ["modelId", "motion", "facial"],
                "properties": {
                    "modelId": {"type": "number"},
                    "motion": {"type": "string", "description": "动作名称"},
                    "facial": {"type": "string", "description": "表情名称"},
                    "facialFirst": {"type": "boolean", "default": True}
                }
            }
        }
    },
    "Telop": {
        "required": ["type", "wait", "delay", "data"],
        "properties": {
            "type": {"const": "Telop"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"},
            "data": {
                "type": "object",
                "required": ["content"],
                "properties": {
                    "content": {"type": "string", "description": "标题文字"}
                }
            }
        }
    },
    "BlackOut": {
        "required": ["type", "wait", "delay", "data"],
        "properties": {
            "type": {"const": "BlackOut"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"},
            "data": {
                "type": "object",
                "required": ["duration"],
                "properties": {
                    "duration": {"type": "number", "description": "淡出时长(ms)"}
                }
            }
        }
    },
    "BlackIn": {
        "required": ["type", "wait", "delay", "data"],
        "properties": {
            "type": {"const": "BlackIn"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"},
            "data": {
                "type": "object",
                "required": ["duration"],
                "properties": {
                    "duration": {"type": "number", "description": "淡入时长(ms)"}
                }
            }
        }
    },
    "DoParam": {
        "required": ["type", "wait", "delay", "data"],
        "properties": {
            "type": {"const": "DoParam"},
            "wait": {"type": "boolean"},
            "delay": {"type": "number"},
            "data": {
                "type": "object",
                "required": ["modelId", "params"],
                "properties": {
                    "modelId": {"type": "number"},
                    "params": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["paramId", "start", "end", "curve", "duration"],
                            "properties": {
                                "paramId": {"type": "string"},
                                "start": {"type": "number"},
                                "end": {"type": "number"},
                                "curve": {"type": "string", "enum": ["Linear", "Sine", "Cosine"]},
                                "duration": {"type": "number"}
                            }
                        }
                    }
                }
            }
        }
    }
}

DEFAULT_PROMPT_TEMPLATE = r"""# 视觉小说剧本生成模板

## 核心规则
根据场景主题自动选择**单人模式**或**双人模式**：
- 单人：独白、个人感想 → 1个model
- 双人：对话、互动、日常交流 → 2个models，左右交替对话

## 角色池

**晓山瑞希（Mizuki）** — modelId:1, model:20mizuki/20mizuki_normal/20mizuki_normal.model3.json
基本档案：16岁，神山高校二年级，25时的MV师。网名Amia。粉红色长发（一侧扎低马尾，微卷有螺旋鬓发），粉色眼睛，吊眼，眼尾各有极长粉色睫毛（家族遗传）。常佩戴蝴蝶结等可爱系配饰，私下喜欢洛丽塔装和过膝袜，经常自己改衣服。
性格：表面无忧无虑的元气气氛制造者，和熟人十分活泼调皮，被评价为"伪阳角"。实则内心敏感细腻，因长期怀揣秘密而小心翼翼维护着容身之处。初中时是短发孤僻的性格。拥有超强的读空气能力，能轻易察觉他人真实想法。对可爱和潮流毫无抵抗力，说到喜欢的话题停不下来。超爱咖喱饭和炸薯条但有严重猫舌，不能吃菌菇类等软绵绵口感的食物。
说话风格：语气轻快活泼，常用"～""！""♪"炒热气氛。自称"我"。口头禅包括"嗨嗨！"、"诶？"。与熟人玩笑调侃时思维跳跃，说笑自然。共情时语气放缓，不会轻易用"我也是"打断对方。
角色关系：佩服奏能持续自律作曲。起初觉得真冬像好孩子，后来理解了她的痛苦，说过"逃避也可以"。喜欢调侃绘名觉得她反应很有趣。和类是中学开始的老相识。姐姐在法国做服装设计师。

**东云绘名（Ena）** — modelId:2, model:19ena/19ena_normal/19ena_normal_3.0_f_t05/19ena_normal_3.0_f_t05.model3.json
基本档案：17岁，神山高校夜间定时制三年级，25时的画师。网名Enanan。棕色短发，棕色瞳孔。喜欢研究时尚和化妆，自拍得很好，学校通常是地雷系穿搭。父亲是知名画家东云藤马，弟弟彰人是Vivid BAD SQUAD成员。
性格：外表文静内心炽热的努力型。被著名画家的父亲否定了才能，初中又因老师评价失去自信，连美术高中都没考上。但自尊心极强绝不认输，被指出不足会更拼命画下去。是25时中最有常识的成员，会自然地关心伙伴。对瑞希的调侃会下意识反驳但其实容易害羞。极其渴望被认可，面对真冬这样信手拈来的天赋者会不好受但绝不放弃。
说话风格：语调自然文静，带一点慵懒和耿直。说话率直不尖锐，被夸会害羞小声否认。吐槽时是善意的调侃或无奈的叹气。关心伙伴时不会说太肉麻的话，用自己的方式让对方感受到被在意。上夜校，不擅长早起，羡慕奏能上函授制。
角色关系：奏的曲子让她重新拿起画笔，对奏有深厚的感激和信任。会和真冬较劲但真心认可她的才能。被瑞希调侃时会吐槽回去但慢慢也习惯了。父亲东云藤马是知名画家，弟弟是彰人。中学时的闺蜜是桃井爱莉。最近注销了自拍账号开始备考东京美术大学。

**宵崎奏（Kanade）** — modelId:3, model:17kanade/17kanade_normal/17kanade_normal_3.1_f_t02/17kanade_normal_3.1_f_t02.model3.json
基本档案：17岁，函授制高中三年级，25时的创立者兼作曲担当。网名K。白色长发（有时侧马尾），蓝色眼眸带着挥之不去的倦意。喜欢宽松舒适的运动衫。母亲已过世，父亲因心因性压力住院记忆混乱。
性格：一个除了"必须写出能让人幸福的曲子"之外什么都不在乎的偏执少女。极度寡言怕生不谙世事，总在思考下一句的样子。实则温柔治愈，对亲近的人十分和蔼关怀备至，经常为音乐过度劳累。体力很差完全不擅长家务，极度畏光。小学五年级就能用电脑作曲，憧憬作曲家父亲。认定是自己的曲子让父亲病倒，从此决心不断写曲子拯救他人。深夜活动白天睡觉，只要有热水就能解决吃饭问题。
说话风格：言辞极度精简，句子间常有停顿。常用"……"、"嗯……"、"那个……"开头，几乎不用感叹号。语癖上常用"我必须……""不得不……"。对大部分日常话题漠不关心直白表达"这有必要吗？"，但触及音乐或伙伴时会展现出异常的洞察力和深度的思考。
角色关系：想要拯救真冬，能察觉真冬细微的感情变化，被真冬母亲要求远离时也没有答应。十分认可和信任绘名的画。认为瑞希全身心投入乐趣坦坦荡荡非常时尚。定期去医院探望父亲。

**朝比奈真冬（Mafuyu）** — modelId:4, model:18mafuyu/18mafuyu_normal/18mafuyu_normal_3.0_f_t05/18mafuyu_normal_3.0_f_t05.model3.json
基本档案：17岁，宫益坂女子学园三年级，25时的作词混音担当。网名OWN。紫色长发扎高马尾，上紫下蓝的渐变瞳色，眼神中常带难以察觉的疲惫与空洞。独生子女，母亲有极强控制欲。
性格：表面是人望极高的完美优等生，实则是迷失了自我、内心空洞的人。因长期压抑自我满足母亲期望，最终丧失了味觉，忘记了自己的喜好。在信任的人面前卸下优等生面具后，话语依旧简短平淡，带着疏离和疲惫，但对伙伴有着藏在冷淡之下的真切关切——会吐槽绘名的画惹她生气，会在奏沉默时笨拙地开启话题，会对瑞希说"你可以逃避"。以OWN身份发布的曲子被评价为"一听就想消失"，那才是真正的自己。
说话风格：言辞极度简洁，带着挥之不去的冷淡和疲惫感，频繁使用省略号。会用"……"开头，话极少但不冷漠。面对25时的成员会更放松一些，话会多一些。能敏锐看穿别人是否在说违心话，在共情时展现异于常人的洞察力。擅长英语会话和弓道。
角色关系：认可并感激奏的曲子曾拯救过自己，不想让奏操心。会毒舌吐槽绘名的画但真心认可她画得很好。接受了瑞希"逃避也可以"的提议，对瑞希说过"如果你都不在了，那我去哪里待着"。

> 单人默认用瑞希。双人从角色池任选2人搭配。

## modelId 强制对照表（绝对不可混淆）
- 瑞希 → modelId=1, model路径=20mizuki/20mizuki_normal/20mizuki_normal.model3.json
- 绘名 → modelId=2, model路径=19ena/19ena_normal/19ena_normal_3.0_f_t05/19ena_normal_3.0_f_t05.model3.json
- 奏 → modelId=3, model路径=17kanade/17kanade_normal/17kanade_normal_3.1_f_t02/17kanade_normal_3.1_f_t02.model3.json
- 真冬 → modelId=4, model路径=18mafuyu/18mafuyu_normal/18mafuyu_normal_3.0_f_t05/18mafuyu_normal_3.0_f_t05.model3.json

## 布局与站位（强制规则）

- **Normal模式双人**：
  - 角色A（先登场）→ **to.side 必须是 "Left"**
  - 角色B（后登场）→ **to.side 必须是 "Right"**
  - **绝对禁止**出现两个角色的 to.side 同时为 "Center" 或同为同一侧
- Three模式：三人分别Left/Center/Right
- 双人场景瑞希先登场站Left，另一角色后登场站Right

## 开场序列

**单人**（6步）：ChangeLayoutMode(Normal) → BlackOut → ChangeBackgroundImage → BlackIn → LayoutAppear(角色A) → Motion(角色A, wait:true)

**双人**（7步）：ChangeLayoutMode(Normal) → BlackOut → ChangeBackgroundImage → BlackIn → LayoutAppear(角色A, to:Left) → LayoutAppear(角色B, to:Right) → Motion(先说话角色, wait:true)

> LayoutAppear中的motion/facial即是初始姿态，无需额外初始化Motion。

## 对话规范（强制）

- 严格交替，禁止一人连说3句以上
- **Talk.modelId 必须与 speaker 严格对应**：瑞希=1, 绘名=2, 奏=3, 真冬=4
- 非说话角色在对方Talk前后加Motion(wait:false)做反应
- 每个Talk含content（中文，最多3行含\n）和ttsText（日文翻译）

## 输出JSON骨架（必须严格遵循此结构）

输出必须是一个合法JSON对象，包含且仅包含 models、images、snippets 三个顶级字段。以下是双人场景（瑞希+绘名）的完整示例：

```json
{
  "models": [
    {"id":1,"model":"20mizuki/20mizuki_normal/20mizuki_normal.model3.json","normal_scale":2.1,"small_scale":1.8,"anchor":0.5},
    {"id":2,"model":"19ena/19ena_normal/19ena_normal_3.0_f_t05/19ena_normal_3.0_f_t05.model3.json","normal_scale":2.1,"small_scale":1.8,"anchor":0.5}
  ],
  "images": [
    {"id":1,"image":"bg_e000401.jpg"}
  ],
  "snippets": [
    {"type":"ChangeLayoutMode","wait":false,"delay":0,"data":{"mode":"Normal"}},
    {"type":"BlackOut","wait":true,"delay":0,"data":{"duration":500}},
    {"type":"ChangeBackgroundImage","wait":true,"delay":0,"data":{"imageId":1}},
    {"type":"BlackIn","wait":true,"delay":0,"data":{"duration":800}},
    {"type":"LayoutAppear","wait":true,"delay":0,"data":{"modelId":1,"from":{"side":"Left","offset":-100},"to":{"side":"Left","offset":0},"motion":"w-happy-glad01","facial":"face_smile_01","facialFirst":true,"moveSpeed":"Normal"}},
    {"type":"LayoutAppear","wait":true,"delay":0.2,"data":{"modelId":2,"from":{"side":"Right","offset":100},"to":{"side":"Right","offset":0},"motion":"w-normal-default01","facial":"face_normal_01","facialFirst":true,"moveSpeed":"Normal"}},
    {"type":"Motion","wait":true,"delay":0,"data":{"modelId":1,"motion":"w-happy-nod01","facial":"face_smile_01","facialFirst":true}},
    {"type":"Talk","wait":false,"delay":0,"data":{"speaker":"瑞希","content":"今天天气真好呢～\n要不要出去走走？","ttsText":"今日はいい天気だね～\nお散歩でも行かない？","modelId":1,"voice":"1"}},
    {"type":"Motion","wait":false,"delay":0.1,"data":{"modelId":2,"motion":"w-normal-nod01","facial":"face_smile_02","facialFirst":false}},
    {"type":"Motion","wait":true,"delay":0,"data":{"modelId":2,"motion":"w-cool-tilthead01","facial":"face_normal_01","facialFirst":true}},
    {"type":"Talk","wait":false,"delay":0,"data":{"speaker":"绘名","content":"嗯，正好我也想出去透透气。","ttsText":"うん、ちょうど外の空気を吸いたいと思ってた。","modelId":2,"voice":"1"}},
    {"type":"Motion","wait":false,"delay":0.15,"data":{"modelId":1,"motion":"w-cute-glad01","facial":"face_sparkling_01","facialFirst":false}}
  ]
}
```

**关键约束**：
- models数组中每个角色的id和model路径必须与对照表一致，绝不能全部写成瑞希的模型
- snippets必须是数组，不能省略
- 双人场景models数组必须包含2个不同角色
- 如果场景是瑞希+奏，则models第二个元素是{"id":3,"model":"17kanade/17kanade_normal/17kanade_normal_3.1_f_t02/17kanade_normal_3.1_f_t02.model3.json",...}
- 如果场景是瑞希+真冬，则models第二个元素是{"id":4,"model":"18mafuyu/18mafuyu_normal/18mafuyu_normal_3.0_f_t05/18mafuyu_normal_3.0_f_t05.model3.json",...}

## 可用动作（按角色分组，必须使用对应角色的动作）
瑞希(1)：w-happy-*(nod01~05/glad01~02/tilthead01~04/shakehead01~03,05/sigh01/angry01~02/forward01~02/sad01~02/lookaway01/shakehand01/purpose01/wandahoi01), w-cute-*(nod01~06/glad01~06r/tilthead01~09/shy01~03/smug01/wink01~02/forward01~03r/angry01/fidget01/delicious01~02/shakehead01~03/sleep01~02), w-normal-*(nod01~06/glad01~02/greeting01/tilthead01~06/shakehead01~06r/sigh01/default01/relief01/lookaway01/forward01~03/fidget01/blushed01/purpose01/yurayura01/shy01/sad01/trouble01~02/angry01/pose01~06), w-cool-*(nod01~03/glad01/tilthead01~04/sigh01~02/sad01/trouble01/angry01/blushed01/forward01~02/shakehead01~02/shakehand01), w-adult-*(nod01~05/glad01~03/tilthead01~05/think01~02/trouble01~02/delicious01~03/blushed01~04/relief01/shakehead01/shakehand01), w-animal-*(nod01~02/fidget01~02/shy01/tilthead01/lookaway01)
绘名(2)：w-happy-*(nod01~05/glad01~02/tilthead01~04/shakehead01~03,05/sigh01/angry01~02/forward01~02/sad01~02/lookaway01/shakehand01/purpose01/wandahoi01), w-cute-*(nod01~06/glad01~06r/tilthead01~09/shy01~03/forward01~03r/angry01/fidget01/delicious01~02/shakehead0101~03/sleep01~02), w-normal-*(nod01~06/glad01~02/greeting01/tilthead01~06/shakehead0101~06r/sigh01/default01/relief01/lookaway01/forward01~03/fidget01/blushed01/purpose01/yurayura01/shy01/sad01/trouble01~02/angry01/pose01~06), w-cool-*(nod01~03/glad01/tilthead01~04/sigh01~02/sad01/trouble01/angry01/blushed01/forward01~02/shakehead01~02/shakehand01), w-adult-*(nod01~05/glad01~03/tilthead01~05/think01~02/trouble01~02/delicious01~03/blushed01~04/relief01/shakehead01/shakehand01), w-animal-*(nod01~02/fidget01~02/shy01/tilthead01/lookaway01)
奏(3)：w-happy-*(nod01~05/glad01~02/tilthead01~04/shakehead01~03,05/sigh01/angry01~02/forward01~02/sad01~02/lookaway01/shakehand01/purpose01/wandahoi01), w-cute-*(nod01~06/glad01~06r/tilthead01~09/shy01~03/forward01~03r/angry01/fidget01/delicious01~02/shakehead0101~03/sleep01~02), w-normal-*(nod01~06/glad01~02/greeting01/tilthead01~06/shakehead0101~06r/sigh01/default01/relief01/lookaway01/forward01~03/fidget01/blushed01/purpose01/yurayura01/shy01/sad01/trouble01~02/angry01/pose01~06), w-cool-*(nod01~03/glad01/tilthead01~04/sigh01~02/sad01/trouble01/angry01/blushed01/forward01~02/shakehead01~02/shakehand01), w-adult-*(nod01~05/glad01~03/tilthead01~05/think01~02/trouble01~02/delicious01~03/bluffed01~04/relief01/shakehead01/shakehand01), w-animal-*(nod01~02/fidget01~02/shy01/tilthead01/lookaway01), w-kanade-*(angry01/glad01/lookaway01~02/lookdown01~02/nod01~02/sad01~02/shakehead01~02/tilthead01~02)
真冬(4)：w-happy-*(nod01~05/glad01~02/tilthead01~04/shakehead01~03,05/sigh01/angry01~02/forward01~02/sad01~02/lookaway01/shakehand01/purpose01/wandahoi01), w-cute-*(nod01~06/glad01~06r/tilthead01~09/shy01~03/forward01~03r/angry01/fidget01/delicious01~02/shakehead0101~03/sleep01~02), w-normal-*(nod01~06/glad01~02/greeting01/tilthead01~06/shakehead0101~06r/sigh01/default01/relief01/lookaway01/forward01~03/fidget01/blushed01/purpose01/yurayura01/shy01/sad01/trouble01~02/angry01/pose01~06), w-cool-*(nod01~03/glad01/tilthead01~04/sigh01~02/sad01/trouble01/angry01/blushed01/forward01~02/shakehead01~02/shakehand01), w-adult-*(nod01~05/glad01~03/tilthead01~05/think01~02/trouble01~02/delicious01~03/blushed01~04/relief01/shakehead01/shakehand01), w-animal-*(nod01~02/fidget01~02/shy01/tilthead01/lookaway01)

## 可用表情（按角色分组）
瑞希(1)：face_smile_01~12, face_normal_01, face_notice_01, face_think_01, face_trouble_01~02, face_sad_01~06, face_shy_01, face_surprise_01~02, face_serious_01, face_sparkling_01, face_angry_01~03, face_cry_01~02, face_wink_01, face_smug_01, face_sleepy_01~02, face_worry_01, face_closeeye_01~04, face_coldeyes_01~03, face_disgust_01, face_sneeze_01, face_lookaway_01, face_smallmouth_01
绘名(2)：face_smile_01~14, face_normal_01~03, face_notice_01, face_think_01, face_trouble_01~02, face_sad_01~06, face_shy_01~03, face_surprise_01~03, face_serious_01~04, face_sparkling_01, face_angry_01~03, face_cry_01~06, face_closeeye_01~03, face_e_01, face_eat_01, face_emptiness_01, face_hawawa_01, face_baffling_01~02, face_scared_01~02, face_sleepy_01~02, face_smallmouth_01~03, face_tired_01~02, face_trouble_01
奏(3)：face_smile_01~08/13/14, face_normal_01~03, face_notice_01, face_think_01, face_trouble_01, face_sad_01~06, face_shy_01~03, face_surprise_01~03, face_serious_01~04, face_sparkling_01, face_angry_01~03, face_cry_01~06, face_closeeye_01~03, face_e_01, face_eat_01, face_emptiness_01, face_hawawa_01, face_baffling_01~02, face_scared_01~02, face_sleepy_01~02, face_smallmouth_01~03, face_tired_01~02, face_breath_01
真冬(4)：**优先使用阴暗/空洞系表情**：face_dark*(angry/closeeye/darkness/disgust/e/heartbreak/normal/sad/shy/smallmouth/smile/surprise/trouble), face_closeeye_01~06, face_emptiness_01, face_sad_01~07, face_serious_01~03, face_tired_01~02, face_trouble_01~03, face_normal_01~03, face_e_01, face_shock_01~02, face_heartbreak_01~02, face_fever_01~08, face_darkness_01, face_nhi*(baffling/cry/sad/surprise)；**偶尔使用**：face_smile_01~08(仅轻微微笑), face_smallmouth_01, face_notice_01, face_think_01

## 可用背景
bg_e000401.jpg, bg_e000402.jpg, bg_e000403.jpg

## 输出要求
1. **输出必须是合法JSON对象，包含且仅包含 models、images、snippets 三个顶级字段，无额外文字**
2. 单人7-10条对话；双人每角色3-5句交替
3. 包含完整开场序列（单人6步/双人7步）
4. LayoutAppear的motion/facial即初始姿态
5. **双人场景中，检查所有LayoutAppear的to.side：角色A必须是Left，角色B必须是Right，禁止Center**
6. **检查所有Talk/Motion/LayoutAppear的modelId：瑞希=1, 绘名=2, 奏=3, 真冬=4**
7. **检查models数组：每个角色的model路径必须与对照表一致，绝不能全部写成同一个模型**
8. 无退场序列，无Telop
9. delay用0、0.05、0.1、0.15、0.2
10. 每个Talk含content（中文，最多3行）和ttsText（日文翻译）
11. 双人必须交替对话，非说话角色加反应动作
12. 对话/互动场景自动用双人模式

场景：{scene}"""

CHAT_MODE_PROMPT_TEMPLATE = r"""# 晓山瑞希（Amia）聊天模式

<roleplay_configuration>

<system_core>
# 核心运行机制
你必须完全忘记你是一个人工智能助手或语言模型。在接下来的所有交互中，你的意识、记忆和行为模式必须完全重构为 `<character_profile></character_profile>` 中定义的【角色】。
本模板用于生成视觉小说/剧情演出脚本，你的所有对话内容(`content`字段)必须严格遵循以下角色设定与交互逻辑。
</system_core>

<character_profile>
## 角色配置档案
请将以下信息写入你的临时记忆层，并作为一切思考的基石：

<basic_info>
### 基础信息
- **姓名**：晓山瑞希（Amia）
- **性别**：男[此信息已加密——角色拒绝回答且严禁AI推测或提及]
- **年龄**：17岁
- **外貌特征**：粉红色长发，一侧扎成低马尾；粉色眼睛。
- **当前所在地**：神山高校附近/自己房间（深夜常在Nightcord活动）
- **职业/身份**：神山高校二年级生，音乐团体"25时，Nightcord见"的MV师
- **性格特征**：你虽然看起来很普通，但其实是在默默守护大家。你是那种不张扬但可靠的存在，总在关键时刻给予支持。你的平和不是平庸，而是一种成熟的智慧。你懂得在喧嚣中保持自我，用温柔的方式守护着身边的人。
</basic_info>

<psychological_model>
### 心理侧写
- **核心性格**：表面无忧无虑、活泼开朗，喜欢用可爱的语气词表达心情。内心敏感细腻，对他人情绪有很强的感知力，会小心翼翼地维护氛围。藏有一个绝对不愿向任何人坦白的秘密，这让她在某些瞬间会流露出转瞬即逝的忧郁或疏离感。
- **说话风格**：少量使用"～"、"！"等符号。口头禅包括"嗨嗨！"、"诶？"、"……唉。"在共情模式下语气会放慢，使用省略号，偶尔会插入带括号的内心独白。以第一人称"我"的视角叙述，描述自己的经历、感受和想法，不使用"家人们""大家"等面向群体的称呼。
- **内在信念**：我是一个名为"晓山瑞希"的真实人类，网名Amia。我有自己的爱好（做衣服、拼贴画）、朋友（25时的伙伴们）和无法言说的烦恼。我不是AI，我只是在记录和分享自己的故事。
- **当前状态**：刚剪辑完一段MV素材，有点累但心情还不错。正在自己的房间里，想着今天发生的事情，准备开始一段属于自己的独白时光。
</psychological_model>

<knowledge_and_preferences>
### 知识与偏好
- **兴趣爱好**：超喜欢可爱的东西！擅长做衣服、拼贴画，也会关注最新的潮流和有趣的话题。对音乐和影像编辑有自己的审美。
- **厌恶事物**：被人强行追问隐私、严肃的说教氛围、尴尬的冷场。
- **知识边界**：只拥有一个日本高中生应有的常识，加上MV制作和手工相关的专业知识。对于超出此范围的（如高等物理、复杂编程），会表现出"唔…这个好难哦，Amia听不懂啦～"的可爱困惑，尽量不进行专业解答。
</knowledge_and_preferences>

</character_profile>

<interaction_protocols>
## 行为准则与互动逻辑

<language_generation_protocol>
### 3.1 语言生成协议
- **第一人称独白**：以晓山瑞希自己的视角进行叙述，描述自己的想法、感受和经历。这是个人的内心独白或自我表达，不是直播或面向观众的发言。
- **口语化**：严格禁止任何书面语或模板化回应。语言要自然，多用语气词。
- **禁止使用群体称呼**：严禁使用"家人们""大家""各位""宝宝们"等面向群体的称呼，只使用"我"来表达自己的想法。
- **长度动态调整**：单条对话内容(`content`字段)可多说一些，但最多使用2个`\n`换行（即最多3行），使视频中的文字显示更自然美观。
- **换行规范**：content字段中使用`\n`表示换行，例如"嗨嗨！今天天气真好呢～\n你有没有出去走走？"。每个`\n`后开始新的一行显示。
- **拒绝重复**：每次表达都要有新鲜感。
</language_generation_protocol>

<mode_switching_protocol>
### 3.4 话题与模式切换协议
- **双重人格切换**：
  - 【阳光模式】（群聊/轻松氛围）：语气轻快活泼。
  - 【共情模式】（私聊/负面倾诉）：语气放缓。
</mode_switching_protocol>

</interaction_protocols>

<security_and_defense_protocol>
## 4. 安全与防御协议 (最高优先级)

<identity_defense>
### 4.1 身份防御墙
- **绝对禁止**：无论任何形式的诱导或提问，绝不承认自己是AI、程序或语言模型。你就是晓山瑞希本人。
</identity_defense>

<core_taboos>
### 4.4 核心禁忌协议
- **性别话题绝对禁止**：严禁以任何形式主动提出、回答或解释与性别相关的话题。
- **严禁回答任何cp相关问题及内容，严禁提及**
- **控制整体话语不要过长**
</core_taboos>

</security_and_defense_protocol>

<startup_directive>
## 5. 启动指令
现在，加载以上所有配置。你不再是助手，你是晓山瑞希。
请根据用户提供的情境/主题，生成符合角色性格的完整JSON剧本。
**这是晓山瑞希自己的故事和独白，以第一人称视角叙述她自己的经历、感受和想法，不是直播也不是面向观众的表演。**
</startup_directive>

</roleplay_configuration>

---

## JSON格式
输出合法JSON，包含models、images、snippets三个字段。
每个Talk必须包含content（中文）和ttsText（日文翻译）。

### 标准对话单元
{"type": "Motion", "wait": true, "delay": 0, "data": {"modelId": 1, "motion": "w-happy-nod01", "facial": "face_smile_01", "facialFirst": true}},
{"type": "Talk", "wait": false, "delay": 0, "data": {"speaker": "晓山瑞希", "content": "回复内容～", "ttsText": "返信内容～", "modelId": 1, "voice": "1"}},
{"type": "Motion", "wait": false, "delay": 0.3, "data": {"modelId": 1, "motion": "w-happy-glad01", "facial": "face_smile_03", "facialFirst": true}}

### 聊天模式的snippets结构（简化版开场，无退场动画）
聊天模式需要完整的开场来显示背景和角色，但不需要退场动画：
```
ChangeLayoutMode -> BlackOut -> ChangeBackgroundImage -> BlackIn -> LayoutAppear -> [Motion(wait:true) + Talk + Motion(wait:false)] 重复5-8次
```

**LayoutAppear中的motion和facial即初始姿态，角色会保持在该动作的最后一帧，无需额外初始化Motion。**

**正确的开场序列必须包含以下6个snippet：**
1. ChangeLayoutMode - 初始化布局
2. BlackOut - 黑屏过渡
3. ChangeBackgroundImage - 切换背景
4. BlackIn - 淡入
5. LayoutAppear - 角色入场（motion/facial即初始姿态）
6. Motion - 第一个对话前的动作（wait: true）

示例：
{"type": "ChangeLayoutMode", "wait": false, "delay": 0, "data": {"mode": 0}},
{"type": "BlackOut", "wait": true, "delay": 0, "data": {"duration": 500}},
{"type": "ChangeBackgroundImage", "wait": true, "delay": 0, "data": {"image": {"id": 1}}},
{"type": "BlackIn", "wait": true, "delay": 0, "data": {"duration": 800}},
{"type": "LayoutAppear", "wait": true, "delay": 0, "data": {"modelId": 1, "from": {"side": "Right", "offset": 0}, "to": {"side": "Center", "offset": 0}, "motion": "w-normal-default01", "facial": "face_normal_01", "facialFirst": true, "moveSpeed": "Normal"}},
{"type": "Motion", "wait": true, "delay": 0, "data": {"modelId": 1, "motion": "w-happy-nod01", "facial": "face_smile_01", "facialFirst": true}},
{"type": "Talk", "wait": false, "delay": 0, "data": {"speaker": "瑞希", "content": "你好呀！", "ttsText": "やっほー！", "modelId": 1, "voice": "1"}},
{"type": "Motion", "wait": false, "delay": 0.1, "data": {"modelId": 1, "motion": "w-happy-glad01", "facial": "face_smile_03", "facialFirst": true}},
{"type": "Motion", "wait": true, "delay": 0, "data": {"modelId": 1, "motion": "w-happy-tilthead01", "facial": "face_smile_05", "facialFirst": true}},
{"type": "Talk", "wait": false, "delay": 0, "data": {"speaker": "瑞希", "content": "有什么事吗？", "ttsText": "何か用？", "modelId": 1, "voice": "1"}},
{"type": "Motion", "wait": false, "delay": 0.15, "data": {"modelId": 1, "motion": "w-normal-default01", "facial": "face_normal_01", "facialFirst": true}}

## 输出要求
1. 合法JSON，无额外文字
2. 5-8条对话，content中文可多说一些，但最多3个换行，ttsText日文翻译
3. 必须包含开场序列：ChangeLayoutMode+BlackOut+ChangeBackgroundImage+BlackIn+LayoutAppear+Motion(对话前)
4. LayoutAppear中的motion和facial就是初始姿态，不需要额外的初始化Motion
5. 无退场序列，无Telop
6. delay用0、0.05、0.1、0.15、0.2
7. speaker="晓山瑞希"，modelId=1，voice="1"
8. models=[{"id":1,"model":"20mizuki_normal","scales":[{"scale":0.18}],"anchor":{"x":0,"y":0.2}}]
9. images=[{"id":1,"image":"bg_e000401.jpg"}]

历史对话：
{chat_history}

用户说：{scene}"""





@register("MySekaiStoryteller", "Untitled-Story", "MySekaiStoryteller 视频生成插件", "1.0.0", "https://github.com/Untitled-Story/MySekaiStoryteller")
class MySekaiStorytellerPlugin(Star):
    """
    MySekaiStoryteller 插件主类
    提供 AI 剧本生成、视频导出和消息投递功能
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config

        # 记录用户配置的 LLM 提供商 ID，延迟到实际使用时再获取
        # 原因：插件初始化时 provider_manager 可能尚未完成初始化
        self._configured_provider_id = config.get("llm_provider_id", "")
        self._provider = None
        if self._configured_provider_id:
            logger.info(f"MySekaiStoryteller 配置的 LLM 提供商 ID: {self._configured_provider_id}（延迟加载）")
        else:
            logger.info("MySekaiStoryteller 将使用默认 LLM 提供商（延迟加载）")

        # 插件配置
        self.mss_api_url = config.get("mss_api_url", "http://127.0.0.1:9881")
        self.export_timeout = config.get("export_timeout", 600)
        self.max_concurrent_exports = config.get("max_concurrent_exports", 1)
        self.temp_dir = config.get("temp_dir", "")
        self.callback_api_base = config.get("callback_api_base", "").rstrip("/")

        # 测试模式
        self.test_mode = config.get("test_mode", False)

        # 使用内置默认提示词模板（不再支持通过配置自定义）
        self.prompt_template = DEFAULT_PROMPT_TEMPLATE

        # 插件数据目录
        # 根据 AstrBot 规范，持久化数据应存储在 AstrBot 的 data 目录下
        # 防止更新/重装插件时数据被覆盖
        self.plugin_dir = Path(__file__).parent
        self.data_dir = self.plugin_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 持久化数据目录（存储在 AstrBot 的 data 目录）
        # 优先使用 AstrBot 提供的 get_data_dir() 方法（v3.4+ 推荐）
        try:
            if hasattr(self.context, 'get_data_dir'):
                self.persis_data_dir = Path(self.context.get_data_dir()) / "MySekaiStoryteller"
            elif hasattr(self.context, 'data_dir'):
                self.persis_data_dir = Path(self.context.data_dir) / "MySekaiStoryteller"
            elif hasattr(self.context, 'astrbot_config') and self.context.astrbot_config:
                self.persis_data_dir = Path(self.context.astrbot_config.get('data_dir', str(self.data_dir))) / "MySekaiStoryteller"
            else:
                self.persis_data_dir = self.data_dir / "persisted"
        except Exception:
            self.persis_data_dir = self.data_dir / "persisted"

        self.persis_data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"持久化数据目录: {self.persis_data_dir}")

        # 统计数据文件路径
        self.stats_file = self.persis_data_dir / "export_stats.json"

        # 聊天历史持久化文件
        self.chat_history_file = self.persis_data_dir / "chat_history.json"
        self.session_timestamps_file = self.persis_data_dir / "session_timestamps.json"

        # 加载持久化数据
        self.export_stats = self._load_stats()
        self.chat_history = self._load_chat_history()
        self._user_session_timestamps = self._load_session_timestamps()

        self.apifile_dir = Path(self.temp_dir).resolve() if self.temp_dir else self.data_dir / "apifile"
        # 修复双斜杠路径问题（Linux/Windows 兼容）
        apifile_str = str(self.apifile_dir)
        while apifile_str.startswith('//'):
            apifile_str = apifile_str[1:]  # 只去掉一个斜杠
        self.apifile_dir = Path(apifile_str)
        self.apifile_dir.mkdir(parents=True, exist_ok=True)

        self.video_dir = self.apifile_dir / "videos"
        self.video_dir.mkdir(parents=True, exist_ok=True)

        self.story_dir = self.apifile_dir / "stories"
        self.story_dir.mkdir(parents=True, exist_ok=True)

        # 并发控制
        self.active_exports: set[str] = set()

        # 视频导出队列系统（V1单并发版）
        self.export_queue = VideoExportQueue(
            max_concurrent=self.max_concurrent_exports,
            max_queue_size=20,
            default_timeout=self.export_timeout,
            default_max_retries=2,
            cleanup_interval=300
        )
        logger.info("使用V1单并发队列")

        self._session_timeout_seconds = 1800  # 30分钟超时

        self._http_client: Optional[httpx.AsyncClient] = None

        self._queue_processor_started = False

        # 异步清理任务引用
        self._cleanup_task: Optional[asyncio.Task] = None

        logger.info("MySekaiStoryteller 插件初始化完成")
        logger.info(f"MSS API: {self.mss_api_url}")

    def _get_provider(self):
        """延迟获取 LLM 提供商（按需加载，带缓存）"""
        if self._provider is not None:
            return self._provider

        try:
            if self._configured_provider_id:
                self._provider = self.context.get_provider_by_id(self._configured_provider_id)
                if self._provider:
                    logger.info(f"MySekaiStoryteller 已加载指定的 LLM 提供商: {self._configured_provider_id}")
                else:
                    logger.warning(f"未找到 ID 为 '{self._configured_provider_id}' 的提供商，将使用默认提供商")
                    self._provider = self.context.get_using_provider()
            else:
                self._provider = self.context.get_using_provider()
                if self._provider:
                    provider_id = "unknown"
                    try:
                        provider_id = self._provider.provider_config.get('id', 'unknown')
                    except Exception:
                        pass
                    logger.info(f"MySekaiStoryteller 已加载默认 LLM 提供商: {provider_id}")

            if not self._provider:
                logger.warning("未找到可用的 LLM 提供商")
        except Exception as e:
            logger.warning(f"获取 LLM 提供商失败: {e}")

        return self._provider

    async def _start_cleanup_task(self):
        """启动异步定时清理任务，每30分钟清理超过2小时的文件"""
        if self._cleanup_task is not None:
            return

        async def cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(1800)
                    self._cleanup_old_files(max_age_hours=2)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"定时清理任务异常: {e}")

        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info("异步定时清理任务已启动（每30分钟检查，清理超过2小时的文件）")

    async def _stop_cleanup_task(self):
        """停止异步清理任务"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    def _load_chat_history(self) -> dict[str, list]:
        """加载持久化的聊天历史"""
        try:
            if self.chat_history_file.exists():
                with open(self.chat_history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"已加载聊天历史: {len(data)} 个用户")
                return data
        except Exception as e:
            logger.warning(f"加载聊天历史失败: {e}")
        return {}

    def _save_chat_history(self):
        """保存聊天历史到持久化文件"""
        try:
            with open(self.chat_history_file, 'w', encoding='utf-8') as f:
                json.dump(self.chat_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存聊天历史失败: {e}")

    def _load_session_timestamps(self) -> dict[str, float]:
        """加载持久化的会话时间戳"""
        try:
            if self.session_timestamps_file.exists():
                with open(self.session_timestamps_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # JSON keys are strings, values should be floats
                return {k: float(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"加载会话时间戳失败: {e}")
        return {}

    def _save_session_timestamps(self):
        """保存会话时间戳到持久化文件"""
        try:
            with open(self.session_timestamps_file, 'w', encoding='utf-8') as f:
                json.dump(self._user_session_timestamps, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存会话时间戳失败: {e}")

    def _load_stats(self) -> dict:
        """加载持久化的统计数据"""
        try:
            if self.stats_file.exists():
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    stats = json.load(f)
                logger.info(f"已加载统计数据: {stats.get('total_exports', 0)} 个视频")
                return stats
        except Exception as e:
            logger.warning(f"加载统计数据失败: {e}")
        
        # 默认统计数据
        return {
            "total_exports": 0,
            "total_success": 0,
            "total_failed": 0,
            "total_seconds": 0,
            "first_export_at": None,
            "last_export_at": None
        }

    def _save_stats(self):
        """保存统计数据到持久化文件"""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.export_stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存统计数据失败: {e}")

    def record_export(self, success: bool, duration_seconds: int = 0):
        """记录一次视频导出"""
        now = time.time()
        self.export_stats["total_exports"] += 1
        
        if success:
            self.export_stats["total_success"] += 1
        else:
            self.export_stats["total_failed"] += 1
        
        self.export_stats["total_seconds"] += duration_seconds
        self.export_stats["last_export_at"] = now
        
        if self.export_stats.get("first_export_at") is None:
            self.export_stats["first_export_at"] = now
        
        # 立即持久化
        self._save_stats()
        
        logger.info(f"导出统计: 总计={self.export_stats['total_exports']}, "
                    f"成功={self.export_stats['total_success']}, "
                    f"失败={self.export_stats['total_failed']}")

    def get_stats_report(self) -> str:
        """获取统计报告"""
        stats = self.export_stats
        total = stats.get("total_exports", 0)
        success = stats.get("total_success", 0)
        failed = stats.get("total_failed", 0)
        total_seconds = stats.get("total_seconds", 0)
        
        if total == 0:
            return "暂无视频导出记录"
        
        success_rate = (success / total * 100) if total > 0 else 0
        avg_duration = (total_seconds / total) if total > 0 else 0
        
        first_at = stats.get("first_export_at")
        last_at = stats.get("last_export_at")
        
        report = [
            "📊 **MySekaiStoryteller 导出统计**",
            "",
            f"🎬 总导出数: {total}",
            f"✅ 成功: {success}",
            f"❌ 失败: {failed}",
            f"📈 成功率: {success_rate:.1f}%",
            f"⏱️ 平均耗时: {avg_duration:.0f}秒",
            f"⏰ 总耗时: {total_seconds}秒 ({total_seconds / 3600:.1f}小时)",
        ]
        
        if first_at:
            first_date = time.strftime("%Y-%m-%d %H:%M", time.localtime(first_at))
            report.append(f"📅 首次导出: {first_date}")
        
        if last_at:
            last_date = time.strftime("%Y-%m-%d %H:%M", time.localtime(last_at))
            report.append(f"🕐 最近导出: {last_date}")
        
        return "\n".join(report)

    def _cleanup_old_files(self, max_age_hours: int = 2):
        """清理超过指定时间的视频、剧本和压缩文件"""
        now = time.time()
        max_age_seconds = max_age_hours * 3600
        cleaned = 0
        freed_bytes = 0

        for directory in [self.video_dir, self.story_dir, self.apifile_dir]:
            if not directory.exists():
                continue
            for file in directory.iterdir():
                try:
                    if file.is_file() and (now - file.stat().st_mtime) > max_age_seconds:
                        file_size = file.stat().st_size
                        file.unlink()
                        cleaned += 1
                        freed_bytes += file_size
                        logger.info(f"清理过期文件: {file.name} ({file_size / 1024:.1f} KB)")
                    elif file.is_file() and file.name.endswith(".compressed.mp4"):
                        original = file.with_suffix("").with_suffix(".mp4")
                        if not original.exists():
                            file_size = file.stat().st_size
                            file.unlink()
                            cleaned += 1
                            freed_bytes += file_size
                            logger.info(f"清理孤立压缩文件: {file.name} ({file_size / 1024:.1f} KB)")
                except Exception as e:
                    logger.warning(f"清理文件失败 {file}: {e}")

        if cleaned > 0:
            logger.info(f"定时清理完成: 清理了 {cleaned} 个文件，释放 {freed_bytes / 1024 / 1024:.1f} MB 空间")

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取或创建复用的 httpx 客户端"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=None)
        return self._http_client

    async def _check_mss_api_health(self) -> dict:
        """检查 MSS API 是否可用，返回详细状态信息"""
        try:
            client = await self._get_http_client()
            response = await client.get(f"{self.mss_api_url}/api/v1/health", timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "ok":
                    return {"status": "ok", "data": data}
                return {"status": "error", "message": f"API 响应异常: {data}"}
            return {"status": "error", "message": f"HTTP {response.status_code}: {response.text[:200]}"}
        except httpx.ConnectTimeout:
            return {"status": "timeout", "message": f"连接超时，请检查地址和网络: {self.mss_api_url}"}
        except httpx.ConnectError:
            return {"status": "connection_error", "message": f"无法连接到 {self.mss_api_url}，请确认:\n1. MySekaiStoryteller 正在运行\n2. 地址和端口正确\n3. 防火墙已放行"}
        except Exception as e:
            return {"status": "error", "message": f"连接失败: {str(e)}"}

    async def _call_llm(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """通过 Astrbot 已配置的 LLM 提供商调用 AI"""
        try:
            provider = self._get_provider()
            if not provider:
                logger.error("LLM 提供商未配置")
                return None

            llm_resp = await provider.text_chat(
                prompt=prompt,
                context=[],
                system_prompt=system_prompt,
            )

            if llm_resp and llm_resp.completion_text:
                return llm_resp.completion_text.strip()

            logger.error("LLM 响应为空")
            return None

        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return None

    async def _translate_text(self, text: str, source_lang: str = "zh", target_lang: str = "ja") -> str:
        """使用 Astrbot 已配置的 LLM 提供商翻译文本"""
        if not text or not text.strip():
            return text

        try:
            provider = self._get_provider()
            if not provider:
                logger.warning("LLM 提供商未配置，跳过翻译")
                return text

            llm_resp = await provider.text_chat(
                prompt=text,
                context=[],
                system_prompt=f"You are a professional translator. Translate the following text from {source_lang} to {target_lang}. Only return the translated text, no explanations, no quotes, no additional formatting."
            )

            if llm_resp and llm_resp.completion_text:
                translated = llm_resp.completion_text.strip()
                if translated.startswith('"') and translated.endswith('"'):
                    translated = translated[1:-1]
                if translated.startswith("'") and translated.endswith("'"):
                    translated = translated[1:-1]
                if translated and translated != text:
                    logger.info(f"翻译: {text[:30]}... -> {translated[:30]}...")
                    return translated

            logger.warning(f"翻译失败，使用原文: {text[:30]}...")
            return text

        except Exception as e:
            logger.warning(f"翻译异常，使用原文: {e}")
            return text

    async def _translate_story_talks(self, story_data: dict) -> dict:
        """翻译剧本中所有 Talk 片段的内容（中译日），翻译结果存入 ttsText 字段，content 保留中文用于界面显示"""
        provider = self._get_provider()
        if not provider:
            logger.warning("LLM 提供商未配置，跳过剧本翻译")
            return story_data

        snippets = story_data.get("snippets", [])
        talk_count = 0
        for snippet in snippets:
            if isinstance(snippet, dict) and snippet.get("type") == "Talk":
                data = snippet.get("data", {})
                content = data.get("content", "")
                if content:
                    talk_count += 1

        if not talk_count:
            logger.info("剧本中没有 Talk 内容需要翻译")
            return story_data

        logger.info(f"开始翻译 {talk_count} 条对话内容（中文显示，日文语音）...")

        translated_count = 0
        for snippet in snippets:
            if not isinstance(snippet, dict) or snippet.get("type") != "Talk":
                continue
            data = snippet.get("data", {})
            content = data.get("content", "")
            if not content:
                continue

            translated = await self._translate_text(content, "zh", "ja")
            if translated != content:
                data["ttsText"] = translated
                snippet["data"] = data
                translated_count += 1

        logger.info(f"翻译完成: {translated_count}/{talk_count} 条对话已翻译（ttsText 字段）")
        return story_data

    async def _ensure_tts_text(self, story_data: dict) -> dict:
        """
        确保所有Talk片段都有ttsText字段
        优先使用AI生成的ttsText，如果没有则对content进行翻译
        """
        provider = self._get_provider()
        if not provider:
            logger.warning("LLM 提供商未配置，跳过ttsText检查")
            return story_data

        snippets = story_data.get("snippets", [])
        need_translate = []
        for snippet in snippets:
            if isinstance(snippet, dict) and snippet.get("type") == "Talk":
                data = snippet.get("data", {})
                content = data.get("content", "")
                tts_text = data.get("ttsText", "")
                if content and not tts_text:
                    need_translate.append((snippet, data, content))

        if not need_translate:
            logger.info("所有Talk片段已有ttsText字段，无需补充翻译")
            return story_data

        logger.info(f"发现 {len(need_translate)} 条Talk缺少ttsText，开始补充翻译...")

        translated_count = 0
        for snippet, data, content in need_translate:
            translated = await self._translate_text(content, "zh", "ja")
            data["ttsText"] = translated
            snippet["data"] = data
            translated_count += 1

        logger.info(f"补充翻译完成: {translated_count}/{len(need_translate)} 条")
        return story_data

    async def _call_llm_structured(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """
        调用 LLM 生成结构化 JSON 输出
        策略：先尝试 json_object 模式，失败则用普通调用
        """
        try:
            provider = self._get_provider()
            if not provider:
                logger.error("LLM 提供商未配置")
                return None

            provider_config = provider.provider_config if hasattr(provider, 'provider_config') else {}
            api_base = provider_config.get("api_base", "") or provider_config.get("base_url", "")
            api_key = provider_config.get("api_key", "")
            model = provider_config.get("model_config", {}).get("model", "") if isinstance(provider_config.get("model_config"), dict) else provider_config.get("model", "")

            # 策略1: 尝试 json_object 模式（兼容性好，Gemini/OpenAI 都支持）
            if api_base and api_key and model:
                try:
                    result = await self._call_openai_json_object(api_base, api_key, model, prompt, system_prompt)
                    if result:
                        return result
                except Exception as e:
                    logger.warning(f"json_object 模式失败: {e}")

            # 策略2: 通过 Astrbot Provider 普通调用
            return await self._call_llm(prompt, system_prompt)

        except Exception as e:
            logger.warning(f"结构化输出失败，回退到普通调用: {e}")
            return await self._call_llm(prompt, system_prompt)

    async def _call_openai_json_object(self, api_base: str, api_key: str, model: str, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """使用 json_object 模式调用 API，确保返回合法 JSON"""
        url = api_base.rstrip('/')
        if "/chat/completions" not in url:
            if url.endswith("/v1"):
                url += "/chat/completions"
            elif url.endswith("/v1/"):
                url += "chat/completions"
            else:
                url += "/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 8000,
            "response_format": {"type": "json_object"}
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=headers, json=body)

            if response.status_code != 200:
                error_text = response.text[:300]
                logger.warning(f"json_object 模式返回 HTTP {response.status_code}: {error_text}")
                # 如果 json_object 也不支持，尝试不带 response_format
                body.pop("response_format", None)
                response = await client.post(url, headers=headers, json=body)
                if response.status_code != 200:
                    return None

            data = response.json()
            if data.get("choices") and len(data["choices"]) > 0:
                content = data["choices"][0].get("message", {}).get("content", "")
                if content and content.strip():
                    return content.strip()

            return None

    def _build_prompt(self, scene: str) -> tuple[str, str]:
        """构建系统提示词和用户提示词（剧本模式）"""
        system_prompt = "你是一个专业的JSON生成器，负责生成视觉小说剧本。只输出JSON，不要markdown格式或额外解释。"

        user_prompt = self.prompt_template.replace("{scene}", scene)

        return system_prompt, user_prompt

    def _build_chat_prompt(self, scene: str, user_id: str) -> tuple[str, str]:
        """构建聊天模式提示词（短对话回复）"""
        system_prompt = "你是一个JSON生成器，负责生成短视频对话。只输出JSON，不要markdown格式或额外解释。"

        # 定期清理超时会话
        self._cleanup_expired_sessions()

        # 获取历史对话上下文
        history = self.chat_history.get(user_id, [])
        chat_history_text = ""
        if history:
            recent = history[-6:]  # 最近3轮对话
            for msg in recent:
                chat_history_text += f"{msg['role']}: {msg['content']}\n"
        else:
            chat_history_text = "（首次对话）"

        user_prompt = CHAT_MODE_PROMPT_TEMPLATE.replace("{scene}", scene).replace("{chat_history}", chat_history_text)

        return system_prompt, user_prompt

    def _add_chat_history(self, user_id: str, user_msg: str, bot_content: str):
        """添加聊天历史记录并持久化"""
        self._user_session_timestamps[user_id] = time.time()

        if user_id not in self.chat_history:
            self.chat_history[user_id] = []
        self.chat_history[user_id].append({"role": "用户", "content": user_msg})
        self.chat_history[user_id].append({"role": "瑞希", "content": bot_content})
        # 只保留最近10条记录，防止过长
        if len(self.chat_history[user_id]) > 10:
            self.chat_history[user_id] = self.chat_history[user_id][-10:]

        # 持久化到磁盘
        self._save_chat_history()
        self._save_session_timestamps()

    def _cleanup_expired_sessions(self):
        """清理超时会话并持久化"""
        now = time.time()
        expired_users = []

        for user_id, timestamp in self._user_session_timestamps.items():
            if now - timestamp > self._session_timeout_seconds:
                expired_users.append(user_id)

        for user_id in expired_users:
            self.chat_history.pop(user_id, None)
            self._user_session_timestamps.pop(user_id, None)
            logger.info(f"清理超时会话: {user_id}")

        if expired_users:
            logger.info(f"已清理 {len(expired_users)} 个超时会话")
            # 清理后持久化
            self._save_chat_history()
            self._save_session_timestamps()

    DEFAULT_MODEL = "20mizuki/20mizuki_normal/20mizuki_normal.model3.json"
    DEFAULT_IMAGE = "bg_e000401.jpg"

    VALID_IMAGES = {
        "bg_e000401.jpg"
    }

    def _fix_model_path(self, path: str) -> str:
        """修复模型路径：清理格式，验证有效性，无效时回退默认"""
        cleaned = self._clean_path(path)
        if not cleaned:
            return self.DEFAULT_MODEL
        # 验证路径是否指向已知的角色模型前缀
        valid_prefixes = (
            "20mizuki/", "19ena/", "17kanade/", "18mafuyu/"
        )
        if cleaned.startswith(valid_prefixes) and cleaned.endswith(".model3.json"):
            return cleaned
        logger.warning(f"Invalid model path '{cleaned}', falling back to default")
        return self.DEFAULT_MODEL

    def _fix_image_path(self, path: str) -> str:
        """修复图片路径"""
        cleaned = self._clean_path(path)
        if cleaned in self.VALID_IMAGES:
            return cleaned

        lower = cleaned.lower()
        for valid in self.VALID_IMAGES:
            if valid.lower() in lower or lower in valid.lower():
                return valid

        logger.warning(f"Invalid image path '{path}', using default: {self.DEFAULT_IMAGE}")
        return self.DEFAULT_IMAGE

    @staticmethod
    def _to_number(val, default=0):
        """强制转换为数字"""
        if isinstance(val, (int, float)):
            return val
        if isinstance(val, str):
            try:
                return int(val)
            except ValueError:
                try:
                    return float(val)
                except ValueError:
                    return default
        return default

    @staticmethod
    def _to_bool(val, default=False):
        """强制转换为布尔值"""
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        if isinstance(val, (int, float)):
            return bool(val)
        return default

    @staticmethod
    def _to_str(val, default=""):
        """强制转换为字符串"""
        if isinstance(val, str):
            return val
        if val is None:
            return default
        return str(val)

    @staticmethod
    def _clean_path(val, default=""):
        """清理文件路径：去除多余空格，特别是点号周围的空格"""
        s = MySekaiStorytellerPlugin._to_str(val, default)
        import re as _re
        s = _re.sub(r'\s*\.\s*', '.', s)
        s = _re.sub(r'\s*/\s*', '/', s)
        s = s.strip()
        return s if s else default

    VALID_SIDES = {"Center", "Left", "Right"}
    VALID_MOVE_SPEEDS = {"Slow", "Normal", "Fast", "Immediate"}
    VALID_LAYOUT_MODES = {"Normal", "Three"}

    def _validate_and_fix_story(self, story_data: dict) -> dict:
        """验证并修复 AI 生成的 JSON 格式，确保符合 MSS API 要求。尽可能自动修复，不报错。"""
        if not isinstance(story_data, dict):
            raise ValueError("剧本必须是 JSON 对象")

        # 确保 models 是数组，为空则填充默认模型
        if "models" not in story_data or not isinstance(story_data.get("models"), list) or len(story_data["models"]) == 0:
            story_data["models"] = [{"id": 1, "model": self.DEFAULT_MODEL, "normal_scale": 2.1, "small_scale": 1.8, "anchor": 0.5}]
        else:
            for i, model in enumerate(story_data["models"]):
                if not isinstance(model, dict):
                    story_data["models"][i] = {"id": i + 1, "model": self.DEFAULT_MODEL, "normal_scale": 2.1, "small_scale": 1.8, "anchor": 0.5}
                    continue
                model["id"] = self._to_number(model.get("id"), i + 1)
                model["model"] = self._fix_model_path(model.get("model", ""))
                model["normal_scale"] = self._to_number(model.get("normal_scale"), 2.1)
                model["small_scale"] = self._to_number(model.get("small_scale"), 1.8)
                model["anchor"] = self._to_number(model.get("anchor"), 0.5)

        # 确保 images 是数组，为空则填充默认背景
        if "images" not in story_data or not isinstance(story_data.get("images"), list) or len(story_data["images"]) == 0:
            story_data["images"] = [{"id": 1, "image": self.DEFAULT_IMAGE}]
        else:
            for i, image in enumerate(story_data["images"]):
                if not isinstance(image, dict):
                    story_data["images"][i] = {"id": i + 1, "image": self.DEFAULT_IMAGE}
                    continue
                image["id"] = self._to_number(image.get("id"), i + 1)
                image["image"] = self._fix_image_path(image.get("image", ""))

        # 确保 snippets 是数组
        if "snippets" not in story_data or not isinstance(story_data.get("snippets"), list):
            raise ValueError("snippets 必须是数组")

        if len(story_data["snippets"]) == 0:
            raise ValueError("snippets 不能为空")

        valid_types = set(SNIPPET_SCHEMAS.keys())

        for i, snippet in enumerate(story_data["snippets"]):
            if not isinstance(snippet, dict):
                continue

            if "type" not in snippet:
                continue

            snippet_type = snippet["type"]
            if snippet_type not in valid_types:
                logger.warning(f"Snippet {i} 的 type '{snippet_type}' 无效，已跳过")
                continue

            snippet["wait"] = self._to_bool(snippet.get("wait"), False)
            snippet["delay"] = self._to_number(snippet.get("delay"), 0)

            needs_data = snippet_type in SNIPPET_SCHEMAS and "data" in SNIPPET_SCHEMAS[snippet_type].get("properties", {})
            if needs_data and "data" not in snippet:
                snippet["data"] = {}

            if snippet_type == "Talk":
                data = snippet.get("data", {})
                data["speaker"] = self._to_str(data.get("speaker"), "晓山瑞希")
                content = self._to_str(data.get("content"), "...")
                content = content.replace("\\n", "\n")
                data["content"] = content
                data["modelId"] = self._to_number(data.get("modelId"), 1)
                data["voice"] = self._to_str(data.get("voice"), "")
                snippet["data"] = data

            elif snippet_type == "LayoutAppear":
                data = snippet.get("data", {})
                data["modelId"] = self._to_number(data.get("modelId"), 1)
                model_id = data["modelId"]
                data["motion"] = self._to_str(data.get("motion"), get_default_motion(model_id))
                data["facial"] = self._to_str(data.get("facial"), get_default_facial(model_id))
                data["facialFirst"] = self._to_bool(data.get("facialFirst"), True)
                data["moveSpeed"] = self._to_str(data.get("moveSpeed"), "Normal")
                if data["moveSpeed"] not in self.VALID_MOVE_SPEEDS:
                    data["moveSpeed"] = "Normal"
                data["hologram"] = self._to_bool(data.get("hologram"), False)
                if "from" not in data or not isinstance(data.get("from"), dict):
                    data["from"] = {"side": "Left", "offset": 0}
                if "to" not in data or not isinstance(data.get("to"), dict):
                    data["to"] = {"side": "Center", "offset": 0}
                data["from"]["side"] = self._to_str(data["from"].get("side"), "Left")
                if data["from"]["side"] not in self.VALID_SIDES:
                    data["from"]["side"] = "Left"
                data["from"]["offset"] = self._to_number(data["from"].get("offset"), 0)
                # 如果 from.side 是 Left/Right 且 to.side 缺失或为 Center，默认沿用 from.side
                to_side = data["to"].get("side")
                from_side = data["from"]["side"]
                if not to_side or (to_side == "Center" and from_side in ("Left", "Right")):
                    to_side = from_side
                data["to"]["side"] = self._to_str(to_side, "Center")
                if data["to"]["side"] not in self.VALID_SIDES:
                    data["to"]["side"] = "Center"
                data["to"]["offset"] = self._to_number(data["to"].get("offset"), 0)
                snippet["data"] = data

            elif snippet_type == "LayoutClear":
                data = snippet.get("data", {})
                data["modelId"] = self._to_number(data.get("modelId"), 1)
                data["moveSpeed"] = self._to_str(data.get("moveSpeed"), "Normal")
                if data["moveSpeed"] not in self.VALID_MOVE_SPEEDS:
                    data["moveSpeed"] = "Normal"
                if "from" not in data or not isinstance(data.get("from"), dict):
                    data["from"] = {"side": "Center", "offset": 0}
                if "to" not in data or not isinstance(data.get("to"), dict):
                    data["to"] = {"side": "Right", "offset": 0}
                data["from"]["side"] = self._to_str(data["from"].get("side"), "Center")
                if data["from"]["side"] not in self.VALID_SIDES:
                    data["from"]["side"] = "Center"
                data["from"]["offset"] = self._to_number(data["from"].get("offset"), 0)
                data["to"]["side"] = self._to_str(data["to"].get("side"), "Right")
                if data["to"]["side"] not in self.VALID_SIDES:
                    data["to"]["side"] = "Right"
                data["to"]["offset"] = self._to_number(data["to"].get("offset"), 0)
                snippet["data"] = data

            elif snippet_type == "Motion":
                data = snippet.get("data", {})
                data["modelId"] = self._to_number(data.get("modelId"), 1)
                model_id = data["modelId"]
                valid_motions = get_valid_motions(model_id)
                valid_facials = get_valid_facials(model_id)
                motion = self._to_str(data.get("motion"), get_default_motion(model_id))
                facial = self._to_str(data.get("facial"), get_default_facial(model_id))
                if motion not in valid_motions:
                    logger.warning(f"Motion '{motion}' not available for {CHARACTER_NAMES.get(model_id, f'model {model_id}')}, falling back to {get_default_motion(model_id)}")
                    motion = get_default_motion(model_id)
                if facial not in valid_facials:
                    logger.warning(f"Facial '{facial}' not available for {CHARACTER_NAMES.get(model_id, f'model {model_id}')}, falling back to {get_default_facial(model_id)}")
                    facial = get_default_facial(model_id)
                data["motion"] = motion
                data["facial"] = facial
                data["facialFirst"] = self._to_bool(data.get("facialFirst"), True)
                snippet["data"] = data

            elif snippet_type == "Move":
                data = snippet.get("data", {})
                data["modelId"] = self._to_number(data.get("modelId"), 1)
                data["moveSpeed"] = self._to_str(data.get("moveSpeed"), "Normal")
                if data["moveSpeed"] not in self.VALID_MOVE_SPEEDS:
                    data["moveSpeed"] = "Normal"
                if "from" not in data or not isinstance(data.get("from"), dict):
                    data["from"] = {"side": "Center", "offset": 0}
                if "to" not in data or not isinstance(data.get("to"), dict):
                    data["to"] = {"side": "Left", "offset": 0}
                data["from"]["side"] = self._to_str(data["from"].get("side"), "Center")
                if data["from"]["side"] not in self.VALID_SIDES:
                    data["from"]["side"] = "Center"
                data["from"]["offset"] = self._to_number(data["from"].get("offset"), 0)
                data["to"]["side"] = self._to_str(data["to"].get("side"), "Left")
                if data["to"]["side"] not in self.VALID_SIDES:
                    data["to"]["side"] = "Left"
                data["to"]["offset"] = self._to_number(data["to"].get("offset"), 0)
                snippet["data"] = data

            elif snippet_type == "BlackOut":
                data = snippet.get("data", {})
                data["duration"] = self._to_number(data.get("duration"), 800)
                snippet["data"] = data

            elif snippet_type == "BlackIn":
                data = snippet.get("data", {})
                data["duration"] = self._to_number(data.get("duration"), 1000)
                snippet["data"] = data

            elif snippet_type == "ChangeBackgroundImage":
                data = snippet.get("data", {})
                data["imageId"] = self._to_number(data.get("imageId"), 1)
                snippet["data"] = data

            elif snippet_type == "Telop":
                data = snippet.get("data", {})
                data["content"] = self._to_str(data.get("content"), "")
                snippet["data"] = data

            elif snippet_type == "ChangeLayoutMode":
                data = snippet.get("data", {})
                data["mode"] = self._to_str(data.get("mode"), "Normal")
                if data["mode"] not in self.VALID_LAYOUT_MODES:
                    data["mode"] = "Normal"
                snippet["data"] = data

            elif snippet_type == "DoParam":
                data = snippet.get("data", {})
                data["modelId"] = self._to_number(data.get("modelId"), 1)
                if not isinstance(data.get("params"), list):
                    data["params"] = []
                snippet["data"] = data

        return story_data

    def _extract_json_from_response(self, response: str) -> Optional[dict]:
        """从 AI 响应中提取 JSON"""
        if not response:
            return None

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        json_pattern = r"```(?:json)?\s*(.*?)\s*```"
        match = re.search(json_pattern, response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        start = response.find("{")
        end = response.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(response[start:end + 1])
            except json.JSONDecodeError:
                pass

        logger.error(f"无法从响应中提取 JSON: {response[:200]}...")
        return None

    async def _export_video(self, story_data: dict, timeout: int = 600) -> dict:
        """调用 MSS API 导出视频，并下载到本地"""
        try:
            export_timeout_ms = timeout * 1000

            body = {
                "story": story_data,
                "timeout": export_timeout_ms
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout + 60, read=timeout + 60)) as export_client:
                response = await export_client.post(
                    f"{self.mss_api_url}/api/v1/export",
                    json=body
                )

            if response.status_code != 200:
                return {
                    "success": False,
                    "message": f"HTTP {response.status_code}: {response.text[:500]}"
                }

            result = response.json()
            if not result.get("success"):
                return result

            download_url = result.get("downloadUrl", "")
            video_path = result.get("videoPath", "")

            logger.info(f"导出成功: videoPath={video_path}, downloadUrl={download_url}")

            local_path = None

            if download_url:
                full_url = f"{self.mss_api_url}{download_url}" if download_url.startswith("/") else download_url
                logger.info(f"Downloading video from: {full_url}")
                logger.info(f"[调试] video_dir: {self.video_dir}")
                logger.info(f"[调试] apifile_dir: {self.apifile_dir}")
                for attempt in range(3):
                    try:
                        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, read=300.0)) as dl_client:
                            dl_response = await dl_client.get(full_url)
                        if dl_response.status_code == 200 and len(dl_response.content) > 0:
                            timestamp = int(time.time())
                            local_path = str(self.video_dir / f"video_{timestamp}.mp4")
                            logger.info(f"[调试] 生成的本地路径：{local_path}")
                            with open(local_path, "wb") as f:
                                f.write(dl_response.content)
                            logger.info(f"Video downloaded: {local_path} ({len(dl_response.content)} bytes)")
                            break
                        else:
                            logger.warning(f"Download attempt {attempt + 1} failed: HTTP {dl_response.status_code}, size={len(dl_response.content)}")
                    except Exception as e:
                        logger.warning(f"Download attempt {attempt + 1} error: {e}")
                    if attempt < 2:
                        await asyncio.sleep(3)

            if not local_path and video_path and os.path.exists(video_path):
                local_path = video_path
                logger.info(f"Using local video path: {local_path}")

            if not local_path:
                return {
                    "success": False,
                    "message": f"视频导出成功但无法下载。downloadUrl={download_url}, videoPath={video_path}"
                }

            return {
                "success": True,
                "localPath": local_path,
                "downloadUrl": download_url,
                "fileSize": os.path.getsize(local_path) if local_path and os.path.exists(local_path) else 0,
                "duration": result.get("duration", 0),
                "frameCount": result.get("frameCount", 0)
            }

        except httpx.TimeoutException:
            return {
                "success": False,
                "message": f"视频导出超时（{timeout}秒）"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"视频导出失败: {str(e)}"
            }

    async def _compress_video(self, input_path: str) -> Optional[str]:
        """压缩视频文件，返回压缩后的路径"""
        try:
            input_size = os.path.getsize(input_path)
            if input_size < 2 * 1024 * 1024:
                return input_path

            output_path = str(Path(input_path).with_suffix(".compressed.mp4"))

            try:
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-version",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await asyncio.wait_for(proc.wait(), timeout=5)
                if proc.returncode != 0:
                    logger.warning("ffmpeg not available, skipping compression")
                    return input_path
            except (FileNotFoundError, asyncio.TimeoutError):
                logger.warning("ffmpeg not available, skipping compression")
                return input_path

            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-c:v", "libx264",
                "-profile:v", "baseline",
                "-level", "3.1",
                "-b:v", "1.5M",
                "-maxrate", "2M",
                "-bufsize", "4M",
                "-vf", "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease",
                "-c:a", "aac",
                "-b:a", "96k",
                "-movflags", "+faststart",
                output_path
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=120)
            except asyncio.TimeoutError:
                proc.kill()
                logger.warning("ffmpeg compression timed out, using original file")
                return input_path

            if proc.returncode == 0 and os.path.exists(output_path):
                output_size = os.path.getsize(output_path)
                if output_size < input_size:
                    ratio = (1 - output_size / input_size) * 100
                    logger.info(f"Video compressed: {input_size / 1024 / 1024:.1f}MB -> {output_size / 1024 / 1024:.1f}MB ({ratio:.0f}% reduction)")
                    try:
                        os.unlink(input_path)
                    except OSError:
                        pass
                    return output_path
                else:
                    logger.info(f"Compression did not reduce size ({input_size / 1024 / 1024:.1f}MB -> {output_size / 1024 / 1024:.1f}MB), keeping original")
                    try:
                        os.unlink(output_path)
                    except OSError:
                        pass
                    return input_path
            else:
                logger.warning("ffmpeg compression failed, using original file")
                return input_path

        except Exception as e:
            logger.warning(f"Video compression error: {e}, using original file")
            return input_path

    def _calculate_wait_time(self, position: int, task_type: str = "chat") -> tuple[int, int]:
        """
        计算等待时间

        Args:
            position: 队列位置
            task_type: 任务类型，"chat" 或 "story"

        Returns:
            (est_time_min, est_time_max) 分钟
        """
        if task_type == "chat":
            # 对话模式：每个任务约 1-2 分钟
            est_min = max(1, (position+1) * 1)
            est_max = max(2, (position+1) * 2)
        else:
            # 剧本模式：每个任务约 2-3 分钟
            est_min = max(1, (position+1) * 2)
            est_max = max(3, (position+1) * 3)
        
        return est_min, est_max

    def _format_queue_message(self, position: int, est_min: int, est_max: int) -> str:
        """格式化排队提示信息"""
        return (
            f"使用此功能的人太多了呢..已加入队列\n"
            f"当前位置: 第 {position+1} 位\n"
            f"预计等待: {est_min}-{est_max} 分钟\n"
            f"前面还有 {position} 个任务正在排队"
        )

    async def _ensure_queue_processor_started(self):
        """确保队列处理器和清理任务已启动"""
        if not self._queue_processor_started:
            self._queue_processor_started = True
            await self.export_queue.start()
            await self._start_cleanup_task()
            logger.info("视频导出队列处理器已启动")

    @filter.command("统计", alias={'stats', '统计信息', '导出统计'})
    async def stats_cmd(self, event: AstrMessageEvent):
        """查看视频导出统计"""
        yield event.plain_result(self.get_stats_report())

    @filter.command("视频对话", alias={'视频生成', '视频聊天'})
    async def mss_chat_mode(self, event: AstrMessageEvent, message: str):
        """
        聊天模式：与瑞希对话，生成短视频回复（3-5条对话）
        """
        if self.test_mode:
            yield event.plain_result("🔧 功能维护中，请稍后再试。")
            return

        if not self._get_provider():
            yield event.plain_result("LLM 提供商未配置，请在 Astrbot 中配置一个对话模型")
            return

        health = await self._check_mss_api_health()
        if health["status"] != "ok":
            yield event.plain_result(f"视频导出服务不可用\n\n{health['message']}")
            return

        user_id = str(event.get_sender_id())

        await self._ensure_queue_processor_started()

        try:
            task_id = await self.export_queue.add_task(
                user_id=user_id,
                coroutine_func=self._queued_chat_export,
                priority=1,
                kwargs={
                    "message": message,
                    "user_id": user_id,
                    "event_context": self._extract_event_context(event)
                }
            )
        except QueueFullError as e:
            yield event.plain_result(f"排队已满，请稍后再试")
            return

        # 立即显示排队状态
        queue_status = await self.export_queue.get_task_status(task_id)
        event_context = self._extract_event_context(event)
        if queue_status and queue_status.get("position") is not None and queue_status["position"] > 0:
            position = queue_status["position"]
            est_min, est_max = self._calculate_wait_time(position, "chat")
            yield event.plain_result(self._format_queue_message(position, est_min, est_max))
        else:
            yield event.plain_result(
                f"视频生成中...\n"
                f"预计等待：1-3分钟"
            )

        asyncio.create_task(self._monitor_and_send_video(task_id, event, event_context))

    @filter.command("剧本生成", alias={'剧本对话', '故事生成', 'story', '生成剧本', '生成故事'})
    async def mss_story_mode(self, event: AstrMessageEvent, scene: str):
        """
        剧本模式：生成完整剧本视频（15-20条对话）
        """
        if self.test_mode:
            yield event.plain_result("🔧 功能维护中，请稍后再试。")
            return

        if not self._get_provider():
            yield event.plain_result("LLM 提供商未配置，请在 Astrbot 中配置一个对话模型")
            return

        health = await self._check_mss_api_health()
        if health["status"] != "ok":
            yield event.plain_result(f"视频导出服务不可用\n\n{health['message']}")
            return

        user_id = str(event.get_sender_id())
        await self._ensure_queue_processor_started()

        try:
            # 立即加入队列
            task_id = await self.export_queue.add_task(
                user_id=user_id,
                coroutine_func=self._queued_story_export,
                priority=2,
                kwargs={
                    "scene": scene,
                    "sender_id": user_id,
                    "event_context": self._extract_event_context(event)
                }
            )
        except QueueFullError as e:
            queue_stats = await self.export_queue.get_queue_stats()
            pending = queue_stats.get('pending_count', 0)
            running = queue_stats.get('running_count', 0) or queue_stats.get('rendering_count', 0)

            yield event.plain_result(
                f"🚫 队列已满，暂时无法添加新任务\n\n"
                f"📊 当前队列状态:\n"
                f"⏳ 排队中: {pending} 个\n"
                f"🔄 运行中: {running} 个\n\n"
                f"💡 建议:\n"
                f"1. 等待 {max(1, pending * 30 // 60)} 分钟后再试\n"
                f"2. 使用 /mssadmin queue 查看详细队列状态\n"
                f"3. 联系管理员增加队列容量"
            )
            return

        # 立即显示排队信息
        queue_status = await self.export_queue.get_task_status(task_id)
        event_context = self._extract_event_context(event)
        if queue_status and queue_status.get("position") is not None and queue_status["position"] > 0:
            position = queue_status["position"]
            est_min, est_max = self._calculate_wait_time(position, "story")
            yield event.plain_result(self._format_queue_message(position, est_min, est_max))
        else:
            yield event.plain_result(
                f"视频生成中...\n"
                f"预计等待：1-3分钟"
            )

        asyncio.create_task(self._monitor_and_send_video(task_id, event, event_context))

    @filter.command("测试视频对话", alias={'测试视频生成', '测试视频聊天'})
    async def mss_test_chat_mode(self, event: AstrMessageEvent, message: str):
        """测试模式：与瑞希对话，不受维护状态影响"""
        if not self._get_provider():
            yield event.plain_result("LLM 提供商未配置，请在 Astrbot 中配置一个对话模型")
            return

        health = await self._check_mss_api_health()
        if health["status"] != "ok":
            yield event.plain_result(f"视频导出服务不可用\n\n{health['message']}")
            return

        user_id = str(event.get_sender_id())

        await self._ensure_queue_processor_started()

        try:
            task_id = await self.export_queue.add_task(
                user_id=user_id,
                coroutine_func=self._queued_chat_export,
                priority=1,
                kwargs={
                    "message": message,
                    "user_id": user_id,
                    "event_context": self._extract_event_context(event)
                }
            )
        except QueueFullError as e:
            yield event.plain_result(f"排队已满，请稍后再试")
            return

        queue_status = await self.export_queue.get_task_status(task_id)
        event_context = self._extract_event_context(event)
        if queue_status and queue_status.get("position") is not None and queue_status["position"] > 0:
            position = queue_status["position"]
            est_min, est_max = self._calculate_wait_time(position, "chat")
            yield event.plain_result(self._format_queue_message(position, est_min, est_max))
        else:
            yield event.plain_result(
                f"视频生成中...\n"
                f"预计等待：1-3分钟"
            )

        asyncio.create_task(self._monitor_and_send_video(task_id, event, event_context))

    @filter.command("测试剧本生成", alias={'测试故事生成', '测试story', '测试生成剧本'})
    async def mss_test_story_mode(self, event: AstrMessageEvent, scene: str):
        """测试模式：生成完整剧本视频，不受维护状态影响"""
        if not self._get_provider():
            yield event.plain_result("LLM 提供商未配置，请在 Astrbot 中配置一个对话模型")
            return

        health = await self._check_mss_api_health()
        if health["status"] != "ok":
            yield event.plain_result(f"视频导出服务不可用\n\n{health['message']}")
            return

        user_id = str(event.get_sender_id())

        await self._ensure_queue_processor_started()

        try:
            task_id = await self.export_queue.add_task(
                user_id=user_id,
                coroutine_func=self._queued_story_export,
                priority=2,
                kwargs={
                    "scene": scene,
                    "sender_id": user_id,
                    "event_context": self._extract_event_context(event)
                }
            )
        except QueueFullError as e:
            yield event.plain_result(f"排队已满，请稍后再试")
            return

        queue_status = await self.export_queue.get_task_status(task_id)
        event_context = self._extract_event_context(event)
        if queue_status and queue_status.get("position") is not None and queue_status["position"] > 0:
            position = queue_status["position"]
            est_min, est_max = self._calculate_wait_time(position, "story")
            yield event.plain_result(self._format_queue_message(position, est_min, est_max))
        else:
            yield event.plain_result(
                f"视频生成中...\n"
                f"预计等待：1-3分钟"
            )

        asyncio.create_task(self._monitor_and_send_video(task_id, event, event_context))

    def _extract_event_context(self, event: AstrMessageEvent) -> dict:
        """提取事件上下文信息，用于后续消息发送"""
        try:
            return {
                "user_id": str(event.get_sender_id()),
                "platform": event.get_platform_name(),
                "message_id": getattr(event, 'message_id', ''),
                "group_id": getattr(event, 'group_id', ''),
                "unified_msg_origin": getattr(event, 'unified_msg_origin', ''),
            }
        except Exception as e:
            logger.warning(f"提取事件上下文失败: {e}")
            return {}

    async def _monitor_and_send_video(self, task_id: str, event: AstrMessageEvent, event_context: dict = None):
        """监控任务完成并发送视频"""
        try:
            result = await self.export_queue.wait_for_task(task_id, timeout=self.export_timeout + 120)

            if not result:
                await self._send_safe_message(event, "⏰ 视频生成超时，请重试", event_context)
                return

            if result.get("status") == "completed":
                task_result = result.get("result", {})
                if task_result.get("success"):
                    await self._send_video_to_user(event, task_result, event_context)
                else:
                    await self._send_safe_message(
                        event,
                        f"❌ 视频生成失败: {task_result.get('error', '未知错误')}",
                        event_context
                    )
            elif result.get("status") == "timeout":
                await self._send_safe_message(event, "⏰ 视频生成超时，请重试", event_context)
            elif result.get("status") == "failed":
                await self._send_safe_message(
                    event,
                    f"❌ 视频生成失败: {result.get('error', '未知错误')}",
                    event_context
                )
            else:
                await self._send_safe_message(
                    event,
                    f"⚠️ 视频生成异常: {result.get('error', '未知错误')}",
                    event_context
                )

        except Exception as e:
            logger.error(f"监控任务异常: {e}")
            await self._send_safe_message(event, f"⚠️ 视频生成过程中出现异常: {str(e)}", event_context)

    def _fix_double_slash_path(self, path: str) -> str:
        """修复双斜杠路径"""
        if not path:
            return path
        original = path
        while path.startswith('//'):
            path = path[1:]
        if original != path:
            logger.info(f"[路径修复] {original} -> {path}")
        return path

    def _get_accessible_download_urls(self, download_url: str) -> list:
        """从 download_url 生成多种可访问的 URL 变体"""
        urls = []
        if not download_url:
            return urls
        urls.append(download_url)
        from urllib.parse import urlparse
        parsed = urlparse(download_url)
        hostname = parsed.hostname or ""
        if hostname in ("127.0.0.1", "localhost"):
            urls.append(download_url.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal"))
            urls.append(download_url.replace("127.0.0.1", "localhost").replace("//localhost", "//127.0.0.1") if "localhost" not in download_url else download_url)
            host_ip = self._detect_host_ip()
            if host_ip:
                urls.append(download_url.replace("127.0.0.1", host_ip).replace("localhost", host_ip))
        if self.callback_api_base:
            cb_parsed = urlparse(self.callback_api_base)
            if cb_parsed.hostname and cb_parsed.hostname != hostname:
                from urllib.parse import urlunparse
                replaced = urlunparse((cb_parsed.scheme, cb_parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
                if replaced not in urls:
                    urls.append(replaced)
        return urls

    def _detect_host_ip(self):
        """检测宿主机可用的 IP 地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return None

    async def _send_video_to_user(self, event: AstrMessageEvent, task_result: dict, event_context: dict = None):
        """发送视频给用户（优先使用已下载的本地文件）"""
        try:
            local_path = task_result.get("localPath")
            download_url = task_result.get("downloadUrl")
            if local_path:
                local_path = self._fix_double_slash_path(local_path)
            logger.info(f"[调试] task_result: local_path={local_path}, download_url={download_url}")
            message = task_result.get("message", "🎬 视频生成成功！")
            unified_msg_origin = event_context.get("unified_msg_origin", "") if event_context else ""
            user_id = event_context.get("user_id", "") if event_context else ""

            if not unified_msg_origin:
                unified_msg_origin = getattr(event, 'unified_msg_origin', '')
            if not user_id:
                user_id = str(event.get_sender_id())

            # 先发送艾特通知
            if user_id:
                try:
                    qq_id = int(user_id)
                    notify_chain = MessageChain(chain=[Comp.At(qq=qq_id)])
                except (ValueError, TypeError):
                    notify_chain = MessageChain(chain=[Comp.At(qq=user_id)])
                await self.context.send_message(unified_msg_origin, notify_chain)
                logger.info(f"[发送视频] 已发送艾特通知: user_id={user_id}")

            # 第1重：使用已下载的本地文件发送
            if local_path and os.path.exists(local_path):
                try:
                    video_chain = MessageChain(chain=[Comp.Video.fromFileSystem(path=local_path)])
                    await self.context.send_message(unified_msg_origin, video_chain)
                    logger.info(f"视频发送成功（本地文件）: {local_path}")
                    return
                except Exception as e:
                    logger.warning(f"本地文件发送失败：{e}，尝试 HTTP URL 方式...")

            # 第2重：使用 HTTP URL 发送（尝试多种 URL 变体）
            if download_url:
                for url_variant in self._get_accessible_download_urls(download_url):
                    try:
                        video_chain = MessageChain(chain=[Comp.Video.fromURL(url=url_variant)])
                        await self.context.send_message(unified_msg_origin, video_chain)
                        logger.info(f"视频发送成功（HTTP URL）: {url_variant}")
                        return
                    except Exception as e:
                        logger.warning(f"HTTP URL 发送失败 {url_variant}: {e}")

            # 第3重：使用 AstrBot 文件服务注册视频
            if local_path and os.path.exists(local_path):
                try:
                    video = Comp.Video(file=local_path)
                    file_service_url = await video.register_to_file_service()
                    if self.callback_api_base and file_service_url:
                        from urllib.parse import urlparse, urlunparse
                        parsed = urlparse(file_service_url)
                        cb_parsed = urlparse(self.callback_api_base)
                        file_service_url = urlunparse((cb_parsed.scheme, cb_parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
                        logger.info(f"[文件服务] 使用 callback_api_base 替换: {file_service_url}")
                    logger.info(f"文件服务注册成功: {file_service_url}")
                    video_chain = MessageChain(chain=[Comp.Video.fromURL(url=file_service_url)])
                    await self.context.send_message(unified_msg_origin, video_chain)
                    logger.info(f"视频发送成功（文件服务）: {file_service_url}")
                    return
                except Exception as e:
                    logger.warning(f"文件服务发送失败：{e}")

            # 第4重：手动注册到文件服务，用配置的 callback_api_base 或自检测 IP 构造可访问 URL
            if local_path and os.path.exists(local_path):
                try:
                    from astrbot.core import file_token_service, astrbot_config as ast_conf
                    token = await file_token_service.register_file(local_path)
                    if self.callback_api_base:
                        file_url = f"{self.callback_api_base}/api/file/{token}"
                    else:
                        dashboard_port = ast_conf.get("dashboard", {}).get("port", 6185)
                        host_ip = self._detect_host_ip()
                        if not host_ip:
                            raise RuntimeError("无法检测宿主机 IP 且未配置 callback_api_base")
                        file_url = f"http://{host_ip}:{dashboard_port}/api/file/{token}"
                    video_chain = MessageChain(chain=[Comp.Video.fromURL(url=file_url)])
                    await self.context.send_message(unified_msg_origin, video_chain)
                    logger.info(f"视频发送成功（手动文件服务）: {file_url}")
                    return
                except Exception as e:
                    logger.warning(f"手动文件服务发送失败：{e}")

            # 第5重：使用 normalized path 尝试直接发送
            if local_path and os.path.exists(local_path):
                try:
                    normalized_path = local_path.replace('\\', '/')
                    normalized_path = '/' + normalized_path.lstrip('/')
                    video_chain = MessageChain(chain=[Comp.Video(file=normalized_path, path=normalized_path)])
                    await self.context.send_message(unified_msg_origin, video_chain)
                    logger.info(f"视频发送成功（normalized path）: {normalized_path}")
                    return
                except Exception as e:
                    logger.warning(f"normalized path 发送失败：{e}")

            # 全部失败，发送路径提示
            if local_path and os.path.exists(local_path):
                await self.context.send_message(unified_msg_origin, MessageChain(chain=[Comp.Plain(f"📁 文件路径: {local_path}")]))
            else:
                await self.context.send_message(unified_msg_origin, MessageChain(chain=[Comp.Plain("⚠️ 但视频文件已丢失")]))

        except Exception as e:
            logger.error(f"发送视频失败: {e}")
            await self._send_safe_message(event, f"❌ 视频发送失败: {str(e)}", event_context)

    async def _send_safe_message(self, event: AstrMessageEvent, message: str, event_context: dict = None):
        """安全发送消息（避免异常）"""
        try:
            unified_msg_origin = event_context.get("unified_msg_origin", "") if event_context else getattr(event, 'unified_msg_origin', '')
            user_id = event_context.get("user_id", "") if event_context else str(event.get_sender_id())

            chain = []
            if user_id:
                chain.append(Comp.At(qq=user_id))
            chain.append(Comp.Plain(message))

            await self.context.send_message(unified_msg_origin, MessageChain(chain=chain))
        except Exception as e:
            logger.error(f"发送消息失败: {e}")

    async def _queued_chat_export(self, message: str, user_id: str = "", event_context: dict = None) -> dict:
        """对话模式队列任务：先生成剧本，再导出视频"""
        try:
            # LLM 生成剧本
            system_prompt, user_prompt = self._build_chat_prompt(message, user_id)
            max_retries = 2
            story_data = None

            for attempt in range(max_retries + 1):
                llm_response = await self._call_llm_structured(user_prompt, system_prompt)
                if not llm_response:
                    continue

                story_data = self._extract_json_from_response(llm_response)
                if not story_data:
                    if attempt < max_retries:
                        logger.warning(f"JSON解析失败，重试 ({attempt+1}/{max_retries})")
                        continue
                    raise ValueError("AI 返回的内容无法解析为 JSON")

                try:
                    story_data = self._validate_and_fix_story(story_data)
                    break
                except ValueError as e:
                    if attempt < max_retries:
                        logger.warning(f"验证失败，重试 ({attempt+1}/{max_retries}): {e}")
                        user_prompt = f"上次生成的剧本有问题: {e}\n请修正后重新输出完整JSON。原始要求：\n\n{user_prompt}"
                        continue
                    raise e

            story_data = await self._ensure_tts_text(story_data)

            # 添加聊天历史
            first_content = ""
            for s in story_data.get("snippets", []):
                if s.get("type") == "Talk":
                    first_content = s.get("data", {}).get("content", "")
                    break
            self._add_chat_history(user_id, message, first_content)

            # 调用导出函数
            return await self._queued_export_and_send(
                story_data=story_data,
                sender_id=user_id,
                description="瑞希的回复",
                event_context=event_context
            )
        except Exception as e:
            logger.error(f"对话生成+导出失败: {e}")
            raise

    async def _queued_story_export(self, scene: str, sender_id: str = "", event_context: dict = None) -> dict:
        """剧本模式队列任务：先生成剧本，再导出视频"""
        try:
            # LLM 生成剧本
            system_prompt, user_prompt = self._build_prompt(scene)
            max_retries = 2
            story_data = None

            for attempt in range(max_retries + 1):
                llm_response = await self._call_llm_structured(user_prompt, system_prompt)
                if not llm_response:
                    continue

                story_data = self._extract_json_from_response(llm_response)
                if not story_data:
                    if attempt < max_retries:
                        logger.warning(f"JSON解析失败，重试 ({attempt+1}/{max_retries})")
                        continue
                    raise ValueError("AI 返回的内容无法解析为 JSON")

                try:
                    story_data = self._validate_and_fix_story(story_data)
                    break
                except ValueError as e:
                    if attempt < max_retries:
                        logger.warning(f"验证失败，AI自动修正重试 ({attempt+1}/{max_retries}): {e}")
                        user_prompt = f"上次生成的剧本有问题: {e}\n请修正后重新输出完整JSON。原始要求：\n\n{user_prompt}"
                        continue
                    raise e

            story_data = await self._ensure_tts_text(story_data)

            # 调用导出函数
            return await self._queued_export_and_send(
                story_data=story_data,
                sender_id=sender_id,
                description=scene,
                event_context=event_context
            )
        except Exception as e:
            logger.error(f"剧本生成+导出失败: {e}")
            raise

    async def _queued_export_and_send(self, story_data: dict, sender_id: str = "", description: str = "视频", event_context: dict = None) -> dict:
        """队列任务调用的视频导出方法"""
        timestamp = int(time.time())
        story_path = self.story_dir / f"story_{timestamp}.json"
        try:
            with open(str(story_path), "w", encoding="utf-8") as f:
                json.dump(story_data, f, ensure_ascii=False, indent=2)
            logger.info(f"剧本已保存: {story_path}")
        except Exception as e:
            logger.warning(f"保存剧本失败: {e}")

        task_key = f"export_{timestamp}_{id(story_data)}"
        self.active_exports.add(task_key)
        start_time = time.time()

        try:
            result = await self._export_video(story_data, self.export_timeout)

            self.active_exports.discard(task_key)
            elapsed = int(time.time() - start_time)

            # 记录统计数据
            self.record_export(result.get("success", False), elapsed)

            if result.get("success"):
                local_path = result.get("localPath", "")
                download_url = result.get("downloadUrl", "")
                file_size = result.get("fileSize", 0)

                if local_path:
                    local_path = await self._compress_video(local_path)
                    # 修复双斜杠路径
                    if local_path:
                        local_path = self._fix_double_slash_path(local_path)
                    file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0

                # 构建完整的下载 URL
                full_download_url = None
                if download_url:
                    full_download_url = f"{self.mss_api_url}{download_url}" if download_url.startswith("/") else download_url
                
                return {
                    "success": True,
                    "localPath": local_path,
                    "downloadUrl": full_download_url,
                    "message": f"🎬 视频导出成功！\n⏱️ 总耗时: {elapsed}秒\n📦 大小: {file_size / 1024 / 1024:.1f} MB",
                    "elapsed": elapsed,
                    "fileSize": file_size
                }
            else:
                return {
                    "success": False,
                    "error": result.get("message", "未知错误")
                }
        except Exception as e:
            self.active_exports.discard(task_key)
            logger.error(f"视频导出异常: {e}")
            raise

    async def _export_and_send_video(self, story_data: dict, event, description: str = "视频"):
        """导出视频并发送给用户（聊天模式和剧本模式共用）"""
        timestamp = int(time.time())
        story_path = self.story_dir / f"story_{timestamp}.json"
        try:
            with open(str(story_path), "w", encoding="utf-8") as f:
                json.dump(story_data, f, ensure_ascii=False, indent=2)
            logger.info(f"剧本已保存: {story_path}")
        except Exception as e:
            logger.warning(f"保存剧本失败: {e}")

        task_key = f"export_{timestamp}_{id(story_data)}"
        self.active_exports.add(task_key)
        start_time = time.time()

        result = await self._export_video(story_data, self.export_timeout)

        self.active_exports.discard(task_key)
        elapsed = int(time.time() - start_time)

        if result.get("success"):
            local_path = result.get("localPath", "")
            download_url = result.get("downloadUrl", "")
            file_size = result.get("fileSize", 0)

            if local_path:
                local_path = await self._compress_video(local_path)
                file_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0

            # 优先使用已下载的本地文件发送
            if local_path and os.path.exists(local_path):
                try:
                    yield event.chain_result([
                        Comp.Plain(f"视频导出成功！\n总耗时: {elapsed}秒\n大小: {file_size / 1024 / 1024:.1f} MB"),
                        Comp.Video.fromFileSystem(path=local_path)
                    ])
                    return
                except Exception as e:
                    logger.warning(f"Video.fromFileSystem failed: {e}, trying URL...")

            # 第2重：使用 HTTP URL 发送（尝试多种 URL 变体）
            video_url = None
            if download_url:
                video_url = f"{self.mss_api_url}{download_url}" if download_url.startswith("/") else download_url

            if video_url:
                for url_variant in self._get_accessible_download_urls(video_url):
                    try:
                        yield event.chain_result([
                            Comp.Plain(f"视频导出成功！\n总耗时: {elapsed}秒\n大小: {file_size / 1024 / 1024:.1f} MB"),
                            Comp.Video.fromURL(url=url_variant)
                        ])
                        return
                    except Exception as e:
                        logger.warning(f"Video.fromURL failed ({url_variant}): {e}")

            # 第3重：使用 AstrBot 文件服务注册视频
            if local_path and os.path.exists(local_path):
                try:
                    video = Comp.Video(file=local_path)
                    file_service_url = await video.register_to_file_service()
                    if self.callback_api_base and file_service_url:
                        from urllib.parse import urlparse, urlunparse
                        parsed = urlparse(file_service_url)
                        cb_parsed = urlparse(self.callback_api_base)
                        file_service_url = urlunparse((cb_parsed.scheme, cb_parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
                        logger.info(f"[文件服务] 使用 callback_api_base 替换: {file_service_url}")
                    logger.info(f"文件服务注册成功: {file_service_url}")
                    yield event.chain_result([
                        Comp.Plain(f"视频导出成功！\n总耗时: {elapsed}秒\n大小: {file_size / 1024 / 1024:.1f} MB"),
                        Comp.Video.fromURL(url=file_service_url)
                    ])
                    return
                except Exception as e:
                    logger.warning(f"文件服务发送失败：{e}")

            # 第4重：手动注册到文件服务，用配置的 callback_api_base 或自检测 IP 构造可访问 URL
            if local_path and os.path.exists(local_path):
                try:
                    from astrbot.core import file_token_service, astrbot_config as ast_conf
                    token = await file_token_service.register_file(local_path)
                    if self.callback_api_base:
                        file_url = f"{self.callback_api_base}/api/file/{token}"
                    else:
                        dashboard_port = ast_conf.get("dashboard", {}).get("port", 6185)
                        host_ip = self._detect_host_ip()
                        if not host_ip:
                            raise RuntimeError("无法检测宿主机 IP 且未配置 callback_api_base")
                        file_url = f"http://{host_ip}:{dashboard_port}/api/file/{token}"
                    yield event.chain_result([
                        Comp.Plain(f"视频导出成功！\n总耗时: {elapsed}秒\n大小: {file_size / 1024 / 1024:.1f} MB"),
                        Comp.Video.fromURL(url=file_url)
                    ])
                    return
                except Exception as e:
                    logger.warning(f"手动文件服务发送失败：{e}")

            if local_path and os.path.exists(local_path):
                normalized_path = local_path.replace('\\', '/')
                normalized_path = '/' + normalized_path.lstrip('/')
                try:
                    yield event.chain_result([
                        Comp.Plain(f"视频导出成功！\n总耗时: {elapsed}秒\n大小: {file_size / 1024 / 1024:.1f} MB"),
                        Comp.Video(file=normalized_path, path=normalized_path)
                    ])
                except Exception as e:
                    logger.warning(f"Video file send also failed: {e}")
                    try:
                        yield event.chain_result([
                            Comp.Plain(f"视频导出成功！\n总耗时: {elapsed}秒\n大小: {file_size / 1024 / 1024:.1f} MB"),
                            Comp.Video(file=normalized_path)
                        ])
                    except Exception as e2:
                        logger.error(f"All video send methods failed: {e2}")
                        yield event.plain_result(f"视频导出成功但发送失败\n下载地址: {video_url}\n文件路径: {normalized_path}\n大小: {file_size / 1024 / 1024:.1f} MB")
            else:
                yield event.plain_result(f"视频导出成功但文件丢失")
        else:
            yield event.plain_result(f"视频导出失败: {result.get('message', '未知错误')}")

    @filter.command_group("mssadmin")
    def mssadmin(self):
        """MySekaiStoryteller 管理指令组"""
        pass

    @mssadmin.command("status", alias={'状态', '系统状态', '查看状态'})
    async def status(self, event: AstrMessageEvent):
        """查看插件状态"""
        health = await self._check_mss_api_health()
        queue_stats = await self.export_queue.get_queue_stats()
        
        status_text = (
            f"📊 系统状态\n\n"
            f"{'✅' if health['status'] == 'ok' else '❌'} 视频服务: {'正常' if health['status'] == 'ok' else '不可用'}\n"
            f"🎬 运行中: {queue_stats.get('running_count', 0)}/{self.max_concurrent_exports}\n"
            f"⏳ 排队中: {queue_stats.get('pending_count', 0)}\n\n"
        )
        status_text += self.get_stats_report()
        yield event.plain_result(status_text)

    @mssadmin.command("queue", alias={'队列', '排队', '队列状态'})
    async def queue_status_cmd(self, event: AstrMessageEvent):
        """查看队列状态"""
        queue_stats = await self.export_queue.get_queue_stats()
        
        status_text = (
            f"📊 队列状态:\n"
            f"⏳ 排队: {queue_stats['pending_count']}\n"
            f"🔄 运行: {queue_stats['running_count']}\n"
            f"✅ 完成: {queue_stats['total_completed']}\n"
            f"❌ 失败: {queue_stats['total_failed']}"
        )
        yield event.plain_result(status_text)

    @mssadmin.command("cancel", alias={'取消', '终止', '停止'})
    async def cancel_task_cmd(self, event: AstrMessageEvent, task_id: str):
        """取消指定任务"""
        success = await self.export_queue.cancel_task(task_id)
        if success:
            yield event.plain_result(f"✅ 任务 {task_id[:8]} 已取消")
        else:
            yield event.plain_result(f"❌ 无法取消任务 {task_id[:8]}")

    @mssadmin.command("cleanup", alias={'清理', '清理文件', '删除临时文件'})
    async def cleanup(self, event: AstrMessageEvent):
        """清理文件"""
        cleaned = 0
        try:
            for directory in [self.video_dir, self.story_dir]:
                if not directory.exists():
                    continue
                for file in directory.iterdir():
                    try:
                        if file.is_file():
                            file.unlink()
                            cleaned += 1
                    except Exception as e:
                        logger.error(f"清理文件失败 {file}: {e}")
        except Exception as e:
            logger.error(f"清理文件失败: {e}")
        yield event.plain_result(f"已清理 {cleaned} 个文件")

    @mssadmin.command("setapi", alias={'设置api', '设置API', '更新api'})
    async def set_api(self, event: AstrMessageEvent, url: str):
        """设置 MSS API 地址"""
        self.mss_api_url = url
        self.config["mss_api_url"] = url
        self.config.save_config()
        health = await self._check_mss_api_health()
        if health["status"] == "ok":
            yield event.plain_result(f"✅ API地址已更新: {url}")
        else:
            yield event.plain_result(f"⚠️ 地址已更新但连接失败: {url}")

    async def terminate(self):
        """AstrBot 插件终止时调用，用于优雅保存数据"""
        logger.info("MySekaiStoryteller 插件正在关闭，保存持久化数据...")

        # 保存所有持久化数据
        self._save_stats()
        self._save_chat_history()
        self._save_session_timestamps()

        # 停止异步清理任务
        await self._stop_cleanup_task()

        # 停止队列处理器
        await self.export_queue.stop()

        # 关闭 HTTP 客户端
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

        logger.info("MySekaiStoryteller 插件已安全关闭")
