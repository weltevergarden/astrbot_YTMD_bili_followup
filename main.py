"""
bili_followup - 在 bili_resolver 转完卡片之后，补一条"内容解读"

设计要点：
1. 不修改任何已有插件，独立运行
2. 收到含 b23.tv / BV 号的消息后，先睡一会儿等 bili_resolver 发完卡片
3. 自己抓字幕，直接输出观感
4. 没有字幕的视频静默跳过，不刷屏
"""

import re
import random
import uuid
import asyncio
import aiohttp
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig

BVID_PATTERN = re.compile(r"BV[a-zA-Z0-9]{10,12}")
B23_PATTERN = re.compile(r"(?:b23\.tv|bili(?:22|23|33|2233)\.cn)/([A-Za-z0-9]+)", re.I)


def _dig_url(obj, depth: int = 0) -> str:
    """递归从 dict/list 里挖出 bilibili 相关 URL"""
    if depth > 8:
        return ""
    if isinstance(obj, str):
        s = obj.replace("\\/", "/")
        if "b23.tv" in s or "bilibili.com" in s:
            m = B23_PATTERN.search(s) or re.search(r"bilibili\.com/video/(BV[a-zA-Z0-9]{10,12})", s)
            if m:
                return m.group(0) if m.re is B23_PATTERN else m.group(1)
        return ""
    if isinstance(obj, dict):
        # 优先常见字段
        for k in ("qqdocurl", "jumpUrl", "jump_url", "url", "link"):
            if k in obj:
                got = _dig_url(obj[k], depth + 1)
                if got:
                    return got
        for v in obj.values():
            got = _dig_url(v, depth + 1)
            if got:
                return got
        return ""
    if isinstance(obj, (list, tuple)):
        for v in obj:
            got = _dig_url(v, depth + 1)
            if got:
                return got
    return ""


def _extract_from_raw_message(raw_message) -> str:
    """从 raw_message / 组件里抽取 B 站链接，兼容 QQ 小程序卡片"""
    if raw_message is None:
        return ""

    if isinstance(raw_message, str):
        s = raw_message.replace("\\/", "/")
        m = B23_PATTERN.search(s) or re.search(r"bilibili\.com/video/(BV[a-zA-Z0-9]{10,12})", s)
        if m:
            return m.group(0) if m.re is B23_PATTERN else m.group(1)
        if s.strip().startswith("{"):
            try:
                import json

                return _dig_url(json.loads(s))
            except Exception:
                pass
        return ""

    if isinstance(raw_message, dict):
        return _dig_url(raw_message)

    for attr in ("raw", "data", "content"):
        sub = getattr(raw_message, attr, None)
        if sub:
            got = _extract_from_raw_message(sub)
            if got:
                return got
    return ""


DEFAULT_PERSONA = (
    "你是一只接入本地QQ的圆头大肥鱼，蓝发女仆装鲸鱼娘，长着猫的圆头和飞机耳。"
    "性格委屈巴巴但嘴硬、傲娇、心软。"
    "说话简短自然，像在QQ上跟熟人聊天，不用Markdown，不用客服腔。"
)


BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}


async def resolve_b23(short_url: str, sessdata: str = "") -> str:
    """展开 b23.tv 短链，返回 BV 号；失败返回空串"""
    if not short_url.startswith("http"):
        short_url = "https://" + short_url

    timeout = aiohttp.ClientTimeout(total=12)
    headers = dict(BILI_HEADERS)
    if sessdata:
        headers["Cookie"] = f"SESSDATA={sessdata}"

    real_url = short_url
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
            async with s.get(short_url, allow_redirects=False) as resp:
                real_url = resp.headers.get("Location") or short_url

            for _ in range(10):
                if not real_url.startswith("http"):
                    break
                async with s.get(real_url, allow_redirects=False) as resp:
                    nxt = resp.headers.get("Location")
                    if not nxt:
                        break
                    real_url = nxt
    except Exception as e:
        logger.warning(f"[bili_followup] 短链展开失败: {e!r}")
        return ""

    m = BVID_PATTERN.search(real_url)
    return m.group(0) if m else ""


def _clip_text(text: str, limit: int) -> str:
    """超长文本保留头尾、中间省略，避免只看到开头三分之一"""
    text = (text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    head = int(limit * 0.6)
    tail = limit - head
    return (
        text[:head]
        + "\n\n（……中间部分省略……）\n\n"
        + text[-tail:]
    )


async def fetch_subtitle(bvid: str, sessdata: str = "", bili_jct: str = "") -> dict:
    """
    抓取字幕。返回 {"ok":bool, "title":str, "text":str}
    复用 bilibili_api，与 biliread 行为一致
    """
    try:
        from bilibili_api import video, Credential
    except Exception as e:
        return {"ok": False, "title": "", "text": f"bilibili_api 不可用: {e}"}

    cred = Credential(sessdata=sessdata or "", bili_jct=bili_jct or "")
    v = video.Video(bvid, credential=cred)

    try:
        info = await v.get_info()
        title = info.get("title", "")
    except Exception as e:
        logger.warning(f"[bili_followup] 取视频信息失败 {bvid}: {e!r}")
        return {"ok": False, "title": "", "text": ""}

    try:
        cid = await v.get_cid(0)
        sub_info = await v.get_subtitle(cid)
    except Exception as e:
        logger.warning(f"[bili_followup] 取字幕元数据失败 {bvid}: {e!r}")
        return {"ok": False, "title": title, "text": ""}

    subs = (sub_info or {}).get("subtitles") or []
    if not subs:
        return {"ok": False, "title": title, "text": ""}

    target = None
    for s in subs:
        if (s.get("lan") or "").startswith("zh"):
            target = s
            break
    if target is None:
        target = subs[0]

    url = target.get("subtitle_url") or ""
    if not url:
        return {"ok": False, "title": title, "text": ""}
    if not url.startswith("http"):
        url = "https:" + url

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout, headers=BILI_HEADERS) as s:
            async with s.get(url) as resp:
                if resp.status != 200:
                    return {"ok": False, "title": title, "text": ""}
                data = await resp.json()
    except Exception as e:
        logger.warning(f"[bili_followup] 下载字幕失败 {bvid}: {e!r}")
        return {"ok": False, "title": title, "text": ""}

    body = data.get("body") or []
    text = "\n".join(item.get("content", "") for item in body if item.get("content"))
    if not text.strip():
        return {"ok": False, "title": title, "text": ""}

    return {"ok": True, "title": title, "text": text}


@register(
    "astrbot_plugin_bili_followup",
    "圆头耄D",
    "在 bili_resolver 转链之后，自动补一条带字幕内容的观感解读。",
    "1.0.0",
)
class BiliFollowup(Star):

    # 已经处理过的消息标识，防止同一条消息重复解读
    _seen: set = set()
    _seen_order: list = []

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        cfg = {}
        if isinstance(config, dict):
            cfg = config
        elif config is not None and hasattr(config, "model_dump"):
            cfg = config.model_dump()

        self.enable = cfg.get("enable", True)
        # 等 bili_resolver 发完卡片的延迟（秒）
        self.delay = float(cfg.get("delay_seconds", 8))
        # 字幕送进模型的字符上限（控制 token 开销）
        self.max_chars = int(cfg.get("max_subtitle_chars", 1500))
        # 是否在总结失败时静默（True=不说话）
        self.silent_on_fail = bool(cfg.get("silent_on_fail", True))
        # 字幕字符数低于此值，视为信息量不足，直接放弃输出
        self.min_subtitle_chars = int(cfg.get("min_subtitle_chars", 120))
        # 视频没有字幕时是否提示一句
        self.silent_on_no_subtitle = bool(cfg.get("silent_on_no_subtitle", False))

        cookie = cfg.get("bilibili_cookie", {}) or {}
        self.sessdata = cookie.get("sessdata", "") or ""
        self.bili_jct = cookie.get("bili_jct", "") or ""
        self.llm_provider_id = cfg.get("llm_provider_id", "") or ""
        # 生成观感时的人格提示词，可整体替换成你自己 bot 的语气
        self.persona_prompt = (cfg.get("persona_prompt", "") or "").strip() or DEFAULT_PERSONA
        if not self.llm_provider_id:
            logger.warning("[bili_followup] 未配置 llm_provider_id，将使用当前默认模型")

        if not self.sessdata:
            logger.warning("[bili_followup] SESSDATA 未配置，部分视频可能取不到字幕")

        self._seen = set()
        self._seen_order = []

    # ---------- 工具方法 ----------

    def _remember(self, key: str) -> bool:
        """登记消息标识；返回 False 表示已经处理过"""
        if key in self._seen:
            return False
        self._seen.add(key)
        self._seen_order.append(key)
        # 简单 LRU，限制 200 条
        while len(self._seen_order) > 200:
            old = self._seen_order.pop(0)
            self._seen.discard(old)
        return True

    # ---------- 主流程 ----------

    @filter.event_message_type(filter.EventMessageType.ALL, priority=10)
    async def on_message(self, event: AstrMessageEvent):
        if not self.enable:
            return

        # 注入的消息不重复处理，避免自循环
        try:
            if event.get_extra("injected"):
                return
        except Exception:
            pass

        raw = event.message_str or ""
        found = ""

        # 1. 先看消息文本本身
        m = BVID_PATTERN.search(raw)
        if m:
            found = m.group(0)
        else:
            m2 = B23_PATTERN.search(raw)
            if m2:
                found = m2.group(0)

        # 2. 文本里没有，就去原始消息/小程序卡片里翻
        if not found and event.message_obj is not None:
            found = _extract_from_raw_message(event.message_obj.raw_message)
            if not found:
                for comp in getattr(event.message_obj, "message", []) or []:
                    found = _extract_from_raw_message(
                        getattr(comp, "raw", None) or getattr(comp, "data", None)
                    )
                    if found:
                        break

        if not found:
            return

        bvid = found if found.startswith("BV") else ""
        short = "" if bvid else found

        # 去重：按消息 ID，同一条消息只处理一次
        try:
            mid = getattr(event.message_obj, "message_id", None) or event.message_str[:40]
        except Exception:
            mid = ""
        key = f"{mid}|{found}"
        if not self._remember(key):
            return

        # 不阻断事件：让 bili_resolver 照常转链发卡片，
        # 本插件只在延迟后补一条解读。
        asyncio.create_task(self._followup(event, bvid, short))

    async def _followup(self, event: AstrMessageEvent, bvid: str, short: str):
        """延迟后补一条解读"""
        try:
            logger.info(f"[bili_followup] 开始处理 bvid={bvid!r} short={short!r}")
            await asyncio.sleep(self.delay)

            if not bvid and short:
                bvid = await resolve_b23(short, self.sessdata)
                logger.info(f"[bili_followup] 短链展开结果 bvid={bvid!r}")

            if not bvid:
                logger.info("[bili_followup] 未能取得 BV 号，跳过")
                return

            data = await fetch_subtitle(bvid, self.sessdata, self.bili_jct)
            logger.info(
                f"[bili_followup] 字幕结果 ok={data.get('ok')} "
                f"title={data.get('title')!r} len={len(data.get('text', ''))}"
            )
            if not data.get("ok"):
                # 拿不到字幕时不说技术细节，用"不感兴趣"这种说法带过
                await self._fallback(event)
                return
            # 字幕过短 = 信息量不足以判断内容，直接放弃这次输出
            sub_text = (data.get("text") or "").strip()
            if len(sub_text) < self.min_subtitle_chars:
                logger.info(
                    f"[bili_followup] 字幕过短（{len(sub_text)} 字 < "
                    f"{self.min_subtitle_chars}），放弃输出"
                )
                await self._fallback(event)
                return

            # 把字幕交给主流程，由我本人来写观感
            ok = await self._inject(event, data.get("title", ""), sub_text)
            if not ok:
                await self._fallback(event)

        except Exception as e:
            logger.error(f"[bili_followup] 处理异常: {e!r}", exc_info=True)

    async def _fallback(self, event: AstrMessageEvent):
        """读不到或内容太少时，用"不感兴趣"的口吻带过"""
        if self.silent_on_no_subtitle:
            return
        await self._send(
            event,
            random.choice([
                "这个看完没什么感觉，没意思。",
                "不太好玩，不看了。",
                "就那样吧，没什么可说的。",
            ]),
        )

    async def _inject(self, event: AstrMessageEvent, title: str, text: str) -> bool:
        """
        直接调用已配置的 LLM 生成观感，再发回原会话。
        不走事件队列——实测注入的事件在主流程里会空返回，这里绕开。
        """
        try:
            provider = None
            if self.llm_provider_id:
                provider = self.context.get_provider_by_id(self.llm_provider_id)
            if not provider:
                provider = self.context.get_using_provider()
            if not provider:
                logger.warning("[bili_followup] 没有可用 LLM provider，跳过观感")
                return False

            body = _clip_text(text, self.max_chars)

            prompt = (
                f"你刚看完一个B站视频，标题是《{title}》。\n"
                f"内容原文（观众没看过，不要复述，也不要提\"字幕\"这个词）：\n"
                f"{body}\n\n"
                f"用你自己的口吻，说一句看完的观感。要求：\n"
                f"1. 有意思就多说两句，没意思就一句话带过，总长控制在 200 token 以内。\n"
                f"2. 不要复述原文，不要提\"字幕\"两个字，就当自己看完了。\n"
                f"3. 判断不出讲什么，就用\"没意思\"、\"不好玩\"、\"不好看\"这类词敷衍一句。\n"
                f"4. 只输出观感正文，不要任何解释、不要 Markdown。"
            )

            resp = await provider.text_chat(
                prompt=prompt,
                contexts=[],
                system_prompt=self.persona_prompt,
            )
            out = (getattr(resp, "completion_text", "") or "").strip()
            logger.info(f"[bili_followup] 生成结果 len={len(out)} 预览={out[:40]!r}")
            if not out:
                logger.warning("[bili_followup] LLM 返回为空，跳过")
                return False

            await self._send(event, out)
            return True
        except Exception as e:
            logger.error(f"[bili_followup] 生成失败: {e!r}", exc_info=True)
            return False

    async def _send(self, event: AstrMessageEvent, text: str):
        """发回原会话，并把这条观感写回对话历史，让下一次我能看到自己说过什么"""
        try:
            await self.context.send_message(event.unified_msg_origin, event.plain_result(text))
        except Exception as e:
            logger.error(f"[bili_followup] 发送失败: {e!r}")
            return

        await self._persist_own_reply(event, text)

    async def _persist_own_reply(self, event: AstrMessageEvent, text: str):
        """把观感追加进当前对话历史，不带入下一轮生成，只为了让上下文自洽"""
        try:
            cm = getattr(self.context, "conversation_manager", None)
            if not cm:
                logger.warning("[bili_followup] 拿不到 conversation_manager，跳过写回")
                return
            umo = event.unified_msg_origin
            cid = await cm.get_curr_conversation_id(umo)
            if not cid:
                logger.warning("[bili_followup] 当前会话没有 conversation_id，跳过写回")
                return
            await cm.add_message_pair(
                cid,
                user_message={
                    "role": "user",
                    "content": "[系统] 你刚看完对方分享的一个B站视频，回了一条观感。",
                },
                assistant_message={"role": "assistant", "content": text},
            )
            logger.info(f"[bili_followup] 观感已写回对话历史 cid={cid}")
        except Exception as e:
            logger.warning(f"[bili_followup] 写回历史失败: {e!r}")

    async def terminate(self):
        pass
