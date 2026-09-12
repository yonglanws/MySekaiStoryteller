#!/usr/bin/env python3
"""提示词构建端到端测试（无需 AstrBot 运行时）。

用 stub 替代 astrbot 模块后加载插件主类，通过真实渲染宿主的资源目录
执行 _build_prompt / _build_chat_prompt，断言：
1. 输出无残留占位符
2. 对照表/动作清单/背景清单来自宿主目录
3. 聊天模式的 model 路径为完整真实路径（简写 bug 已修复）

用法：先启动渲染宿主，再执行
  python scripts/test-prompt-build.py [宿主地址，默认 http://127.0.0.1:9881]
"""

import asyncio
import re
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "astrbot_plugin_msst"
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# astrbot stub：只提供 import main.py 所需的最小表面
# ---------------------------------------------------------------------------
astrbot = types.ModuleType("astrbot")
api = types.ModuleType("astrbot.api")
event_mod = types.ModuleType("astrbot.api.event")
star_mod = types.ModuleType("astrbot.api.star")
comp_mod = types.ModuleType("astrbot.api.message_components")


class _Dummy:
    def __init__(self, *args, **kwargs):
        pass


def _passthrough_decorator(*args, **kwargs):
    def wrap(func):
        return func

    return wrap


class _FakeCommandGroup:
    """@filter.command_group 装饰器返回值：携带 .command 子装饰器"""

    def command(self, *args, **kwargs):
        return _passthrough_decorator


def _command_group_decorator(*args, **kwargs):
    def wrap(func):
        return _FakeCommandGroup()

    return wrap


event_mod.filter = types.SimpleNamespace(
    command=_passthrough_decorator,
    command_group=_command_group_decorator,
)
event_mod.AstrMessageEvent = _Dummy
event_mod.MessageEventResult = _Dummy
event_mod.MessageChain = _Dummy
star_mod.Context = _Dummy
star_mod.Star = _Dummy
star_mod.register = _passthrough_decorator


def _noop(*args, **kwargs):
    pass


api.logger = types.SimpleNamespace(info=_noop, warning=_noop, error=_noop, debug=_noop)
api.AstrBotConfig = dict
api.event = event_mod
api.message_components = comp_mod
astrbot.api = api
astrbot.api.event = event_mod
astrbot.api.star = star_mod
astrbot.api.message_components = comp_mod

sys.modules.update(
    {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.event": event_mod,
        "astrbot.api.star": star_mod,
        "astrbot.api.message_components": comp_mod,
    }
)

from astrbot_plugin_msst import main  # noqa: E402
from astrbot_plugin_msst.resource_catalog import ResourceCatalog  # noqa: E402

PLACEHOLDER_RE = re.compile(r"\{[a-z_][a-z0-9_]*\}")


class MinimalSelf:
    """只提供 prompt 构建所需的最小宿主表面，复用插件类的真实方法。"""

    prompt_template = main.DEFAULT_PROMPT_TEMPLATE
    _cleanup_expired_sessions = main.MySekaiStorytellerPlugin._cleanup_expired_sessions
    _build_character_pool = main.MySekaiStorytellerPlugin._build_character_pool
    _build_prompt = main.MySekaiStorytellerPlugin._build_prompt
    _build_chat_prompt = main.MySekaiStorytellerPlugin._build_chat_prompt

    def __init__(self, base_url: str):
        self._catalog = ResourceCatalog(base_url)
        self.chat_history = {}
        self._user_session_timestamps = {}
        self._session_timeout_seconds = 1800

    def _save_chat_history(self):
        pass

    def _save_session_timestamps(self):
        pass


async def run(base_url: str) -> int:
    s = MinimalSelf(base_url)
    data = await s._catalog.refresh(force=True)
    view = s._catalog.view()
    if not view.models:
        print("FAIL: 宿主资源目录为空，请确认宿主已启动且支持 /api/v1/resources")
        return 1

    fails = []

    def check(name, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail else ""))
        if not cond:
            fails.append(name)

    # --- 剧本模式 ---
    system_prompt, user_prompt = s._build_prompt("深夜在Nightcord，大家在赶MV")
    leftovers = set(PLACEHOLDER_RE.findall(user_prompt))
    check("剧本 prompt 无残留占位符", not leftovers, f"残留: {sorted(leftovers)}")
    check("剧本 prompt 含对照表", "modelId=1" in user_prompt and ".model3.json" in user_prompt)
    check("剧本 prompt 含真实模型路径", view.models[0]["path"] in user_prompt)
    check("剧本 prompt 含动作清单", "可用动作" in user_prompt and f"{view.models[0].get('shortName', '')}(1)" in user_prompt)
    check("剧本 prompt 含背景清单", view.data.get("images", [])[0] in user_prompt)
    check("剧本 prompt 含场景", "深夜在Nightcord" in user_prompt)
    check("剧本 prompt 无旧版四段式路径", "19ena_normal_3.0_f_t05/19ena_normal" not in user_prompt)

    # --- 聊天模式 ---
    _, chat_prompt = s._build_chat_prompt("你好呀", "test-user")
    leftovers = set(PLACEHOLDER_RE.findall(chat_prompt))
    check("聊天 prompt 无残留占位符", not leftovers, f"残留: {sorted(leftovers)}")
    chat_defaults = view.chat_defaults()
    check("聊天 prompt 模型为完整真实路径", f'"model":"{chat_defaults["model_path"]}"' in chat_prompt)
    check("聊天 prompt 无简写路径 bug", '"model":"20mizuki_normal"' not in chat_prompt)
    check("聊天 prompt 含默认角色", chat_defaults["name"] in chat_prompt)
    check("聊天 prompt 含场景", "你好呀" in chat_prompt)

    print("\n" + ("ALL PROMPT BUILD TESTS PASSED" if not fails else f"{len(fails)} FAILED"))
    return 1 if fails else 0


if __name__ == "__main__":
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9881"
    code = asyncio.run(run(base_url))
    sys.exit(code)
