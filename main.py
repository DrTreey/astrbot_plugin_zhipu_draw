"""智谱画图 —— 让 Bot 用智谱 CogView 免费画图。

- 手动：/画图 一只橘猫趴在窗台上晒太阳，水彩风
- 自动：聊天里说「帮我画一只……」，由 LLM 调用 generate_image 工具
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.star.filter.command import GreedyStr

API_URL = "https://open.bigmodel.cn/api/paas/v4/images/generations"

# 智谱官方允许的尺寸
SIZE_CHOICES = (
    "1024x1024",
    "768x1344",
    "864x1152",
    "1344x768",
    "1152x864",
    "1440x720",
    "720x1440",
)

# 常见错误码 → 给用户看的话
ERROR_HINTS = {
    "1000": "鉴权失败，检查 API Key 是否填对",
    "1001": "API Key 无效或已失效",
    "1002": "API Key 已过期，请到智谱控制台重新生成",
    "1113": "账户余额不足，免费额度可能用完了",
    "1301": "内容安全审核没通过，换个说法再试试",
    "1302": "请求太频繁，等几秒再来",
    "1303": "并发超限，缓一缓再画",
    "1304": "今日调用次数达到上限",
    "1305": "生成超时，描述太复杂的话可以简化一下",
}


def _guess_ext(raw: bytes) -> str:
    """按文件头判断真实格式，智谱有时回 JPEG 而不是 PNG。"""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if raw[:2] == b"\xff\xd8":
        return ".jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return ".png"


@register(
    "astrbot_plugin_zhipu_draw",
    "Tree",
    "用智谱 CogView 免费画图：/画图 指令 + AI 自动配图，无需显卡、无需中转。",
    "1.0.0",
    "https://github.com/Tree/astrbot_plugin_zhipu_draw",
)
class ZhipuDraw(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.save_dir = str(
            self.config.get("save_dir") or "/AstrBot/data/plugin_data/astrbot_plugin_zhipu_draw"
        )
        os.makedirs(self.save_dir, exist_ok=True)
        self._sem = asyncio.Semaphore(self.max_concurrency)
        self._last_call: dict[str, float] = {}
        self._session: aiohttp.ClientSession | None = None
        logger.info(
            "[zhipu_draw] 已加载：模型=%s，尺寸=%s，key=%s"
            % (self.model, self.size, "已配置" if self.api_key else "未配置")
        )

    # ---------- 配置 ----------

    @property
    def api_key(self) -> str:
        return str(self.config.get("api_key", "") or "").strip()

    @property
    def model(self) -> str:
        return str(self.config.get("model", "cogview-3-flash") or "cogview-3-flash").strip()

    @property
    def size(self) -> str:
        size = str(self.config.get("size", "1024x1024") or "1024x1024").strip()
        return size if size in SIZE_CHOICES else "1024x1024"

    @property
    def quality(self) -> str:
        quality = str(self.config.get("quality", "standard") or "standard").strip().lower()
        return "hd" if quality == "hd" else "standard"

    @property
    def timeout(self) -> int:
        try:
            return max(10, int(self.config.get("timeout", 120)))
        except (TypeError, ValueError):
            return 120

    @property
    def cooldown(self) -> int:
        try:
            return max(0, int(self.config.get("cooldown_seconds", 10)))
        except (TypeError, ValueError):
            return 10

    @property
    def max_concurrency(self) -> int:
        try:
            return max(1, int(self.config.get("max_concurrency", 2)))
        except (TypeError, ValueError):
            return 2

    @property
    def max_keep_files(self) -> int:
        try:
            return max(10, int(self.config.get("max_keep_files", 200)))
        except (TypeError, ValueError):
            return 200

    @property
    def allow_auto_draw(self) -> bool:
        value = self.config.get("allow_auto_draw", True)
        if isinstance(value, str):
            return value.strip().lower() not in ("false", "0", "no", "off", "")
        return bool(value)

    # ---------- 会话 ----------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def terminate(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("[zhipu_draw] 已卸载")

    # ---------- 生成 ----------

    def _check_cooldown(self, key: str) -> int:
        """返回还要等几秒，0 表示可以画。"""
        if self.cooldown <= 0:
            return 0
        last = self._last_call.get(key, 0)
        left = self.cooldown - (time.time() - last)
        return int(left) + 1 if left > 0 else 0

    async def _request_image(self, prompt: str) -> str:
        """调用接口拿图片直链，失败重试两次。"""
        payload = {"model": self.model, "prompt": prompt, "size": self.size}
        if self.model.startswith("cogview-4"):
            payload["quality"] = self.quality
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        session = await self._get_session()
        last_error = ""
        for attempt in range(3):
            try:
                async with session.post(API_URL, json=payload, headers=headers) as resp:
                    body = await resp.text()
                    if resp.status == 200:
                        data = json.loads(body)
                        items = data.get("data") or []
                        if items and items[0].get("url"):
                            return items[0]["url"]
                        last_error = "接口没有返回图片"
                    elif resp.status in (429, 500, 502, 503, 504):
                        last_error = f"服务端 {resp.status}"
                    else:
                        last_error = self._format_error(body, resp.status)
                        if "内容" in last_error or "审核" in last_error:
                            raise RuntimeError(last_error)
            except asyncio.TimeoutError:
                last_error = "请求超时"
            except aiohttp.ClientError as exc:
                last_error = f"网络错误：{exc}"
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(last_error or "未知错误")

    @staticmethod
    def _format_error(body: str, status: int) -> str:
        try:
            data = json.loads(body)
            err = data.get("error") or {}
            code = str(err.get("code") or "")
            msg = str(err.get("message") or "").strip()
            hint = ERROR_HINTS.get(code)
            if hint:
                return f"{hint}（{code}）"
            if msg:
                return f"接口返回 {status}：{msg[:120]}"
        except json.JSONDecodeError:
            pass
        return f"接口返回 {status}"

    async def _generate(self, prompt: str, key: str = "") -> str:
        if not self.api_key:
            raise RuntimeError("还没有配置智谱 API Key，去插件配置里填一下")
        wait = self._check_cooldown(key)
        if wait:
            raise RuntimeError(f"画得有点快，{wait} 秒后再来")
        async with self._sem:
            image_url = await self._request_image(prompt)
            session = await self._get_session()
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"下载图片失败：{resp.status}")
                raw = await resp.read()
        self._last_call[key] = time.time()
        path = os.path.join(self.save_dir, f"{uuid.uuid4().hex}{_guess_ext(raw)}")
        with open(path, "wb") as f:
            f.write(raw)
        self._cleanup()
        logger.info(f"[zhipu_draw] 生成成功 {len(raw)} 字节 → {path}")
        return path

    def _cleanup(self) -> None:
        """只保留最近的若干张，避免容器越跑越胖。"""
        try:
            files = [
                os.path.join(self.save_dir, name)
                for name in os.listdir(self.save_dir)
                if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
            ]
            if len(files) <= self.max_keep_files:
                return
            files.sort(key=os.path.getmtime)
            for path in files[: len(files) - self.max_keep_files]:
                os.remove(path)
        except OSError as exc:
            logger.warning(f"[zhipu_draw] 清理旧图片失败：{exc}")

    # ---------- 指令 ----------

    @filter.command(
        "画图",
        alias={"绘图", "画画", "智谱画图", "cogview"},
        desc="用智谱 CogView 生成图片",
    )
    async def draw_command(self, event: AstrMessageEvent, prompt: GreedyStr):
        text = str(prompt or "").strip()
        if not text:
            yield event.plain_result(
                "画什么？写在指令后面就行，比如：\n/画图 一只橘猫趴在窗台上晒太阳，水彩画风"
            )
            return
        key = event.unified_msg_origin
        try:
            yield event.plain_result(f"在画了：{text}")
            path = await self._generate(text, key)
            yield event.image_result(path)
        except Exception as exc:  # noqa: BLE001 - 要把失败原因告诉用户
            logger.error(f"[zhipu_draw] 画图失败：{exc}")
            yield event.plain_result(f"没画成：{exc}")

    # ---------- LLM 工具 ----------

    @filter.llm_tool(name="generate_image")
    async def generate_image(self, event: AstrMessageEvent, prompt: str):
        """根据文字描述画一张图并发给用户。用户要求画画、配图、出图、来一张图时使用。

        Args:
            prompt(string): 必填。画面描述，尽量具体：主体、动作、场景、光线、画风。
        """
        if not self.allow_auto_draw:
            return "自动配图已关闭，请让用户手动发送 /画图 指令。"
        text = str(prompt or "").strip()
        if not text:
            return "缺少画面描述，无法作画。"
        try:
            path = await self._generate(text, event.unified_msg_origin)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[zhipu_draw] 工具调用失败：{exc}")
            return f"画图失败：{exc}"
        await event.send(MessageChain().file_image(path))
        return f"已按描述画好并发送给用户：{text}"
