"""渲染宿主资源目录客户端 —— 插件的"角色注册表"数据源。

从渲染宿主的 GET /api/v1/resources 拉取资源目录（模型/角色/动作/表情/背景/语音/BGM），
为提示词构建与故事校验提供唯一事实来源。本模块不依赖 astrbot，可独立测试。
"""

import time

import httpx

CATALOG_TTL_SECONDS = 300
FETCH_TIMEOUT_SECONDS = 10.0

# 目录不可用时的最小兜底（保证插件可降级工作：prompt 有锚点、校验只放行默认值）
FALLBACK_CATALOG: dict = {
    "models": [
        {
            "id": 1,
            "name": "晓山瑞希",
            "shortName": "瑞希",
            "path": "20mizuki/20mizuki_normal/20mizuki_normal.model3.json",
            "motions": [],
            "facials": [],
            "defaultMotion": "w-normal-default01",
            "defaultFacial": "face_smile_01",
        }
    ],
    "images": ["bg_e000401.jpg"],
    "voices": [],
    "bgm": [],
}


def _model_prefix(motion_name: str) -> str:
    """w-happy-nod01 -> w-happy-"""
    parts = motion_name.split("-")
    return "-".join(parts[:-1]) + "-" if len(parts) > 1 else motion_name


def _facial_prefix(facial_name: str) -> str:
    """face_smile_01 -> face_smile"""
    parts = facial_name.rsplit("_", 1)
    return parts[0] if len(parts) > 1 else facial_name


def _summarize_names(names: list, prefix_fn) -> str:
    """把长名单压缩为"前缀（种类数）: 样例1、样例2"的形式，控制 prompt 长度。"""
    if not names:
        return "（目录暂未提供）"
    groups: dict[str, list] = {}
    for name in names:
        groups.setdefault(prefix_fn(name), []).append(name)
    lines = []
    for prefix in sorted(groups):
        samples = "、".join(sorted(groups[prefix])[:2])
        lines.append(f"{prefix}*（{len(groups[prefix])}个，如 {samples}）")
    return "，".join(lines)


class ResourceCatalog:
    """从渲染宿主拉取并缓存资源目录。"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._data: dict | None = None
        self._fetched_at: float = 0.0
        self._client: httpx.AsyncClient | None = None

    async def refresh(self, force: bool = False) -> dict:
        """拉取目录；成功刷新缓存，失败时沿用上一次数据（无数据则用兜底）。"""
        now = time.monotonic()
        if not force and self._data is not None and now - self._fetched_at < CATALOG_TTL_SECONDS:
            return self._data

        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS)
            resp = await self._client.get(f"{self.base_url}/api/v1/resources")
            resp.raise_for_status()
            body = resp.json()
            if body.get("success") and isinstance(body.get("models"), list):
                self._data = body
                self._fetched_at = now
        except Exception:  # noqa: BLE001 —— 目录拉取失败必须静默降级
            pass

        if self._data is None:
            self._data = FALLBACK_CATALOG
            self._fetched_at = now
        return self._data

    def view(self) -> "CatalogView":
        """同步快照视图（若无数据先返回兜底；正常流程先 await refresh()）。"""
        return CatalogView(self._data or FALLBACK_CATALOG)


class CatalogView:
    """资源目录快照：prompt 构建与故事校验的统一数据面。"""

    def __init__(self, data: dict):
        self.data = data
        self.models: list[dict] = [m for m in data.get("models", []) if m.get("path")]

    # ----- 基础查询 -----

    def model_by_id(self, model_id) -> dict | None:
        for m in self.models:
            if m.get("id") == model_id:
                return m
        return None

    def default_model(self) -> dict:
        return self.models[0] if self.models else self.model_by_id(1) or {}

    def default_model_path(self) -> str:
        return self.default_model().get("path", FALLBACK_CATALOG["models"][0]["path"])

    def default_image(self) -> str:
        images = self.data.get("images") or []
        return images[0] if images else FALLBACK_CATALOG["images"][0]

    def short_name(self, model: dict) -> str:
        return model.get("shortName") or model.get("name") or f"model{model.get('id')}"

    def name_by_id(self, model_id) -> str:
        m = self.model_by_id(model_id)
        return self.short_name(m) if m else f"model{model_id}"

    # ----- 校验白名单 -----

    def valid_model_paths(self) -> set:
        return {m["path"] for m in self.models}

    def valid_images(self) -> set:
        return set(self.data.get("images") or [])

    def valid_motions(self, model_id) -> set:
        """返回该角色动作集合；空集合表示"目录未提供，不校验"。"""
        m = self.model_by_id(model_id)
        return set(m.get("motions") or []) if m else set()

    def valid_facials(self, model_id) -> set:
        m = self.model_by_id(model_id)
        return set(m.get("facials") or []) if m else set()

    def default_motion(self, model_id) -> str:
        m = self.model_by_id(model_id)
        return (m.get("defaultMotion") if m else "") or "w-normal-default01"

    def default_facial(self, model_id) -> str:
        m = self.model_by_id(model_id)
        return (m.get("defaultFacial") if m else "") or "face_smile_01"

    # ----- prompt 文本块 -----

    def model_table(self) -> str:
        lines = []
        for m in self.models:
            lines.append(f"- {self.short_name(m)} → modelId={m['id']}, model路径={m['path']}")
        return "\n".join(lines)

    def id_mapping(self) -> str:
        return ", ".join(f"{self.short_name(m)}={m['id']}" for m in self.models)

    def motion_list(self) -> str:
        lines = []
        for m in self.models:
            lines.append(f"{self.short_name(m)}({m['id']})：{_summarize_names(m.get('motions') or [], _model_prefix)}")
        return "\n".join(lines)

    def facial_list(self) -> str:
        lines = []
        for m in self.models:
            lines.append(f"{self.short_name(m)}({m['id']})：{_summarize_names(m.get('facials') or [], _facial_prefix)}")
        return "\n".join(lines)

    def image_list(self) -> str:
        return ", ".join(self.data.get("images") or [])

    def model_ref(self, model_id) -> str:
        """角色池档案首行引用：modelId:N, model:路径"""
        m = self.model_by_id(model_id)
        if not m:
            return f"modelId:{model_id}"
        return f"modelId:{m['id']}, model:{m['path']}"

    def example_models_block(self, ids: list) -> str:
        """JSON 示例中的 models 数组内容（按给定 id 顺序）。"""
        entries = []
        for model_id in ids:
            m = self.model_by_id(model_id) or self.default_model()
            entries.append(
                '{"id":%s,"model":"%s","normal_scale":2.1,"small_scale":1.8,"anchor":0.5}'
                % (m.get("id"), m.get("path"))
            )
        return ",\n    ".join(entries)

    def chat_defaults(self) -> dict:
        """聊天模式默认角色（目录第一个模型）。"""
        m = self.default_model()
        return {
            "name": m.get("name", "晓山瑞希"),
            "short_name": self.short_name(m),
            "model_path": m.get("path", ""),
            "default_motion": self.default_motion(m.get("id")),
            "default_facial": self.default_facial(m.get("id")),
        }
