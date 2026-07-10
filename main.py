import asyncio
import re
import copy
import json
import html
import base64
import io
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import ipaddress

import aiohttp
from croniter import croniter

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.event import MessageChain
from astrbot.api.star import Context, Star, StarTools
from astrbot.api import logger, AstrBotConfig
import astrbot.api.message_components as Comp

try:
    from PIL import Image as PILImage, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


# ==================== 本地渲染：动态字体发现 ====================

# 中文字体名关键字（优先级从高到低），用于从系统字体中筛选
_CJK_FONT_KEYWORDS = [
    "noto sans cjk", "noto sans sc", "source han sans",  # Noto / 思源
    "microsoft yahei", "msyh",                            # 微软雅黑
    "pingfang", "ping fang",                               # 苹方
    "simhei", "heiti",                                     # 黑体
    "wqy", "wenquanyi",                                    # 文泉驿
    "droid sans fallback",                                 # Droid
    "simsun", "songti",                                    # 宋体
    "kaiti", "simkai",                                     # 楷体
    "fang",                                                # 仿宋
]

# 系统字体扫描目录
_FONT_SCAN_DIRS = [
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "C:/Windows/Fonts",
    "/System/Library/Fonts",
    "/Library/Fonts",
    Path.home() / ".local/share/fonts",
    Path.home() / ".fonts",
]


def _discover_cjk_font() -> str | None:
    """动态发现系统中可用的中文字体，优先使用 fc-list，回退到文件系统扫描"""
    # 策略 1: 使用 fc-list（Linux/macOS 常用）
    font = _discover_via_fc_list()
    if font:
        return font
    # 策略 2: 扫描常见字体目录
    return _discover_via_scan()


def _discover_via_fc_list() -> str | None:
    """通过 fc-list 命令查找中文字体"""
    try:
        result = subprocess.run(
            ["fc-list", ":lang=zh", "--format=%{file}\n"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        candidates = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not candidates:
            return None
        # 按关键字优先级排序
        for kw in _CJK_FONT_KEYWORDS:
            for path in candidates:
                if kw in path.lower():
                    return path
        # 没有匹配关键字，返回第一个可用的
        return candidates[0]
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return None


def _discover_via_scan() -> str | None:
    """扫描文件系统中常见字体目录，查找中文字体文件"""
    font_files: list[str] = []
    for scan_dir in _FONT_SCAN_DIRS:
        scan_path = Path(scan_dir)
        if not scan_path.is_dir():
            continue
        try:
            for f in scan_path.rglob("*"):
                if f.suffix.lower() in (".ttf", ".ttc", ".otf") and f.is_file():
                    font_files.append(str(f))
        except (PermissionError, OSError):
            continue
    if not font_files:
        return None
    # 按 CJK 关键字优先级筛选
    for kw in _CJK_FONT_KEYWORDS:
        for path in font_files:
            if kw in path.lower():
                return path
    # 兜底：返回任意找到的字体（至少能渲染英文数字）
    return font_files[0] if font_files else None


def _wrap_text(text: str, font, max_width: int, max_lines: int | None = 2) -> list[str]:
    """将文本按像素宽度自动换行，超出 max_lines 时截断并添加省略号"""
    lines: list[str] = []
    remaining = text.replace("\n", " ").replace("\r", "").strip()
    if not remaining:
        return []
    while remaining and (max_lines is None or len(lines) < max_lines):
        is_last = max_lines is not None and len(lines) == max_lines - 1
        line = ""
        consumed = 0
        for i, char in enumerate(remaining):
            candidate = line + char
            if font.getlength(candidate) > max_width:
                break
            line = candidate
            consumed = i + 1
        else:
            lines.append(remaining)
            remaining = ""
            break
        if not line:
            line = remaining[0]
            remaining = remaining[1:]
        else:
            remaining = remaining[consumed:]
        if is_last and remaining:
            while line and font.getlength(line + "…") > max_width:
                line = line[:-1]
            line += "…"
        lines.append(line)
    return lines


# ==================== HTML 模板 ====================

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  html {
    width: 100%;
  }

  body {
    font-family: "Noto Sans SC", "Source Han Sans SC", "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "Droid Sans Fallback", "SimHei", "Helvetica Neue", Arial, sans-serif;
    padding: 24px;
    width: 100%;
    min-height: 100vh;
  }

  .page {
    width: 100%;
    max-width: 1200px;
    margin: 0 auto;
  }

  /* ========== 浅色模式 ========== */
  body.light {
    background: linear-gradient(145deg, #e8eaf0, #dde1ea, #d0d5e0);
    color: #333;
  }

  body.light .header h1 {
    color: #1a1a2e;
  }

  body.light .game-card {
    background: rgba(255, 255, 255, 0.45);
    border: 1px solid rgba(255, 255, 255, 0.7);
    border-top: 1px solid rgba(255, 255, 255, 0.9);
  }

  body.light .game-status.free { color: #2e7d32; }
  body.light .game-status.upcoming { color: #e65100; }
  body.light .game-title { color: #111; }
  body.light .game-desc { color: #555; }
  body.light .price-original { color: #999; }
  body.light .price-current-free { color: #2e7d32; }
  body.light .price-current-upcoming { color: #e65100; }
  body.light .footer { color: #aaa; }
  body.light .empty-hint { color: #999; }

  /* ========== 深色模式 (Steam 风格) ========== */
  body.dark {
    background: linear-gradient(145deg, #171a21, #1b2838, #1e2d40);
    color: #c7d5e0;
  }

  body.dark .header h1 {
    color: #66c0f4;
  }

  body.dark .game-card {
    background: rgba(30, 50, 70, 0.45);
    border: 1px solid rgba(102, 192, 244, 0.12);
    border-top: 1px solid rgba(102, 192, 244, 0.2);
  }

  body.dark .game-status.free { color: #66bb6a; }
  body.dark .game-status.upcoming { color: #ffa726; }
  body.dark .game-title { color: #e5e5e5; }
  body.dark .game-desc { color: #8f98a0; }
  body.dark .price-original { color: #626f78; }
  body.dark .price-current-free { color: #66bb6a; }
  body.dark .price-current-upcoming { color: #ffa726; }
  body.dark .footer { color: #4c6070; }
  body.dark .empty-hint { color: #4c6070; }

  /* ========== 通用布局 ========== */
  .header {
    text-align: center;
    margin-bottom: 22px;
  }

  .header h1 {
    font-size: 24px;
    font-weight: 700;
  }

  .game-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 28px;
  }

  /* 液态玻璃卡片 */
  .game-card {
    border-radius: 16px;
    min-width: 0;
    overflow: hidden;
    padding: 14px;
    backdrop-filter: blur(40px) saturate(180%);
    -webkit-backdrop-filter: blur(40px) saturate(180%);
    transition: transform 0.2s ease;
  }

  .game-status {
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 8px;
    line-height: 1.4;
    overflow-wrap: anywhere;
  }

  .game-cover {
    width: 100%;
    aspect-ratio: 16 / 10;
    object-fit: cover;
    display: block;
    border-radius: 10px;
    margin-bottom: 10px;
  }

  .game-title {
    font-size: 18px;
    font-weight: 700;
    margin-bottom: 8px;
    line-height: 1.4;
    overflow-wrap: anywhere;
  }

  .game-desc {
    font-size: 14px;
    line-height: 1.7;
    margin-bottom: 10px;
    overflow-wrap: anywhere;
  }

  .game-price {
    font-size: 14px;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .price-original {
    text-decoration: line-through;
    font-size: 14px;
  }

  .price-current-free {
    font-weight: 700;
    font-size: 15px;
  }

  .price-current-upcoming {
    font-weight: 700;
    font-size: 15px;
  }

  .footer {
    text-align: center;
    margin-top: 20px;
    font-size: 11px;
  }

  .empty-hint {
    text-align: center;
    padding: 30px;
    font-size: 14px;
    grid-column: 1 / -1;
  }
  @media (max-width: 560px) {
    body { padding: 16px; }
    .game-grid { grid-template-columns: 1fr; gap: 18px; }
  }
</style>
</head>
<body class="{{ theme }}">
  <main class="page">
  <div class="header">
    <h1>Epic免费游戏</h1>
  </div>

  <div class="game-grid">
    {% for game in all_games %}
    <div class="game-card">
      {% if game.is_free_now %}
      <div class="game-status free">现在免费，结束日期: {{ game.free_end }}</div>
      {% else %}
      <div class="game-status upcoming">即将推出，开始: {{ game.free_start }} ~ 结束: {{ game.free_end }}</div>
      {% endif %}

      {% if game.cover %}
      <img class="game-cover" src="{{ game.cover }}" alt="cover" />
      {% endif %}

      <div class="game-title">{{ game.title }}</div>
      <div class="game-desc">{{ game.description }}</div>
      <div class="game-price">
        {% if game.original_price_desc and game.original_price_desc != "0" %}
        <span class="price-original">{{ game.original_price_desc }}</span>
        {% endif %}
        {% if game.is_free_now %}
        <span class="price-current-free">免费</span>
        {% else %}
        <span class="price-current-upcoming">{{ game.original_price_desc }}</span>
        {% endif %}
      </div>
    </div>
    {% endfor %}

    {% if not all_games %}
    <div class="empty-hint">暂无免费游戏数据 🎮</div>
    {% endif %}
  </div>

  <div class="footer">
    Epic Games 周免游戏推送 · by xiaoruange39 · Powered by AstrBot
  </div>
  </main>
</body>
</html>
'''


class EpicFreeGamePlugin(Star):
    """Epic Games 每周免费游戏推送插件

    功能：
    1. /epic 指令：手动查询当前 Epic 免费游戏
    2. 定时推送：根据 Cron 表达式自动推送到配置好的目标
    """

    # 备用 API 列表，依次尝试
    FALLBACK_APIS = [
        "https://60s.viki.moe/v2/epic",
        "https://api.60s.viki.moe/v2/epic",
    ]

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.api_url: str = config.get("api_url", "https://60s.viki.moe/v2/epic")
        self.cron_time: str = config.get("cron_time", "")
        self.enable_cache: bool = config.get("enable_cache", True)
        self.dark_mode: bool = config.get("dark_mode", True)
        self.show_loading_message: bool = config.get("show_loading_message", True)
        self.render_mode: str = config.get("render_mode", "自动")

        # 从配置中读取推送目标列表
        push_targets_raw = config.get("push_targets", [])
        if isinstance(push_targets_raw, list):
            self.push_targets: list[str] = [t.strip() for t in push_targets_raw if isinstance(t, str) and t.strip()]
        else:
            self.push_targets: list[str] = []

        # 数据目录（使用框架提供的 StarTools.get_data_dir()）
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_epic_freegame")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 缓存文件路径
        self.cache_path = self.data_dir / "epic_free_cache.json"

        # 定时任务句柄
        self._cron_task: asyncio.Task | None = None

        # 字体缓存（本地渲染用）
        self._font_path: str | None = None
        self._font_searched: bool = False

        # 尝试在初始化时启动定时任务（应对 Web UI 修改配置后的热重载场景）
        # 热重载时 __init__ 是在运行的异步上下文中调用的，而 on_loaded 生命周期事件不会再触发
        try:
            loop = asyncio.get_running_loop()
            if self.cron_time:
                self._start_cron_task()
                logger.info(f"Epic 免费游戏定时推送已在热重载时随配置更新启动, Cron: {self.cron_time}")
        except RuntimeError:
            # 冷启动阶段可能尚未初始化好运行中循环，交予 on_loaded 生命周期触发
            pass

        # 共享 HTTP 会话（延迟初始化，复用 TCP 连接池）
        self._http_session: aiohttp.ClientSession | None = None

    @filter.on_astrbot_loaded()
    async def on_loaded(self):
        """AstrBot 首次初始化完成后启动定时任务"""
        if self.cron_time and (self._cron_task is None or self._cron_task.done()):
            self._start_cron_task()
            logger.info(f"Epic 免费游戏定时推送已随框架启动激活, Cron: {self.cron_time}")
        elif not self.cron_time:
            logger.info("未配置 Cron 表达式，Epic 免费游戏定时推送未启用")

    # ==================== 指令 ====================

    @filter.command("epic")
    async def cmd_epic(self, event: AstrMessageEvent):
        '''查询当前 Epic 免费游戏'''
        if self.show_loading_message:
            yield event.plain_result("正在获取 Epic 免费游戏信息，请稍候... 🎮")

        try:
            games = await self._fetch_games()
            if not games:
                yield event.plain_result("未获取到任何游戏数据 😢")
                return

            try:
                image_comp = await self._render_games(games)
                if image_comp is None:
                    # 纯文字模式
                    yield event.plain_result(self._format_games_as_text(games))
                else:
                    yield event.chain_result([image_comp])
            except Exception as render_err:
                logger.warning(f"Epic 免费游戏图片渲染失败，切换为文本模式: {render_err}")
                text_result = self._format_games_as_text(games)
                yield event.plain_result(f"【⚠️ 渲染失败，已切换为文本模式】\n\n{text_result}")

        except Exception as e:
            logger.error(f"获取 Epic 免费游戏信息失败: {e}")
            yield event.plain_result("获取 Epic 免费游戏信息失败，请稍后重试 😢")

    # ==================== 核心逻辑 ====================

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取共享的 HTTP 会话（延迟初始化，加锁防竞态）"""
        if getattr(self, "_session_lock", None) is None:
            self._session_lock = asyncio.Lock()
            
        async with self._session_lock:
            if self._http_session is None or self._http_session.closed:
                self._http_session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=15)
                )
            return self._http_session

    async def _fetch_games(self) -> list[dict] | None:
        """从 API 获取 Epic 免费游戏数据，支持备用 API 自动回退"""
        # 构建尝试顺序：用户配置的 API 优先，然后是备用 API
        apis_to_try = []
        if self.api_url:
            apis_to_try.append(self.api_url)
        for api in self.FALLBACK_APIS:
            if api not in apis_to_try:
                apis_to_try.append(api)

        if not apis_to_try:
            logger.warning("未配置 API 地址且无可用备用 API")
            return None

        last_error = None
        session = await self._get_session()
        # 强制使用 identity (无压缩) 以彻底解决 Brotli 解码问题。
        # 即使 server 忽略此头，identity 也是最通用的。
        headers = {
            "Accept-Encoding": "identity",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        for api_url in apis_to_try:
            try:
                async with session.get(api_url, headers=headers) as resp:
                    if resp.status != 200:
                        logger.warning(f"API {api_url} 请求失败，状态码: {resp.status}")
                        continue
                    data = await resp.json()

                # 安全解析：确保 data 类型正确，避免 AttributeError
                if isinstance(data, list):
                    games = data
                elif isinstance(data, dict):
                    games = data.get("data", [])
                else:
                    logger.warning(f"API {api_url} 返回了意外的数据类型: {type(data).__name__}")
                    games = []
                # 轻量数据清洗：仅保留 dict 类型的有效游戏条目
                games = [g for g in games if isinstance(g, dict)]
                if not games:
                    logger.info(f"API {api_url} 未返回有效游戏数据，尝试下一个")
                    continue

                return games

            except Exception as e:
                logger.warning(f"API {api_url} 请求出错: {e}")
                last_error = e
                continue

        if last_error:
            logger.error(f"所有 API 均请求失败，最后一个错误: {last_error}")
            raise last_error

        logger.info("所有 API 均未返回游戏数据")
        return None

    async def _sanitize_cover_url(self, url: str) -> str:
        """校验封面图 URL，防止 SSRF 攻击（包含 DNS 级防护）"""
        if not url or not isinstance(url, str):
            return ""
        try:
            parsed = urlparse(url)
            # 仅允许 https 协议
            if parsed.scheme != "https":
                return ""
            hostname = parsed.hostname or ""
            # 拒绝常见本地/内网回环域名
            blocked_hostnames = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
            hostname_lower = hostname.lower()
            if hostname_lower in blocked_hostnames or hostname_lower.endswith(".local"):
                return ""
            # DNS 解析获取真实 IP，防假公网域名指向内网 (预防 DNS Rebinding)
            try:
                loop = asyncio.get_running_loop()
                addr_info = await loop.getaddrinfo(hostname, None)
                for res in addr_info:
                    ip_str = res[4][0]
                    ip = ipaddress.ip_address(ip_str)
                    # 严防全系非公网通信地址
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified or not getattr(ip, 'is_global', True):
                        return ""
            except Exception:
                # 解析失败或无效记录，直接拒绝
                return ""
            return url
        except Exception:
            return ""

    # ==================== 渲染 ====================

    @staticmethod
    def _game_sort_key(g: dict):
        """排序键: 正在免费 > 即将免费，再按开始时间升序"""
        free_start = g.get("free_start_at", 0)
        if free_start is None:
            return (not g.get("is_free_now", False), 0)
        try:
            return (not g.get("is_free_now", False), int(free_start))
        except (ValueError, TypeError):
            pass
        try:
            dt_str = str(free_start).replace("Z", "+00:00")
            dt = datetime.fromisoformat(dt_str)
            return (not g.get("is_free_now", False), int(dt.timestamp()))
        except (ValueError, TypeError):
            pass
        return (not g.get("is_free_now", False), 0)

    def _find_font(self) -> str | None:
        """动态查找系统中可用的中文字体（结果会缓存）"""
        if self._font_searched:
            return self._font_path
        self._font_searched = True
        self._font_path = _discover_cjk_font()
        if self._font_path:
            logger.info(f"本地渲染将使用字体: {self._font_path}")
        else:
            logger.warning("未找到可用的中文字体，本地渲染将不可用。建议安装: apt install fonts-noto-cjk")
        return self._font_path

    async def _render_games(self, games: list[dict]) -> Comp.Image | None:
        """根据 render_mode 分发到对应渲染器，返回 Image 组件或 None（纯文字模式）"""
        if self.render_mode == "纯文字":
            return None  # 调用方会处理纯文字输出
        elif self.render_mode == "本地渲染":
            if not HAS_PILLOW:
                raise RuntimeError("Pillow 未安装，无法使用本地渲染模式")
            return await self._render_games_local(games)
        elif self.render_mode == "API渲染":
            return await self._render_games_api(games)
        else:  # 自动: 先尝试 API，失败后回退本地
            try:
                return await self._render_games_api(games)
            except Exception as e:
                logger.warning(f"API 渲染失败，尝试切换到本地渲染: {e}")
                if HAS_PILLOW:
                    return await self._render_games_local(games)
                raise

    async def _render_games_api(self, games: list[dict]) -> Comp.Image:
        """使用框架 html_render 渲染，返回 URL 形式的 Image 组件"""
        render_games = copy.deepcopy(games)

        for game in render_games:
            game["title"] = html.escape(str(game.get("title", "")))
            raw_desc = str(game.get("description", ""))
            clean_desc = re.sub(r'\[/?[a-zA-Z0-9]+\]', '', raw_desc)
            game["description"] = html.escape(clean_desc)
            game["original_price_desc"] = html.escape(str(game.get("original_price_desc", "")))
            game["free_start"] = html.escape(str(game.get("free_start", "")))
            game["free_end"] = html.escape(str(game.get("free_end", "")))
            safe_cover = await self._sanitize_cover_url(game.get("cover", ""))
            game["cover"] = html.escape(safe_cover, quote=True)

        all_games = sorted(render_games, key=self._game_sort_key)

        render_data = {
            "all_games": all_games,
            "theme": "dark" if self.dark_mode else "light",
        }

        options = {
            "full_page": True,
            "type": "jpeg",
            "quality": 90,
            "animations": "disabled",
            "timeout": 60_000,
        }

        # 使用 return_url=True（默认）获取框架托管的 HTTP URL
        # QQ 适配器（NapCat/LLOneBot）要求通过 URL 传输富媒体
        image_url = await self.html_render(
            HTML_TEMPLATE,
            render_data,
            return_url=True,
            options=options,
        )

        return Comp.Image.fromURL(image_url)

    async def _download_cover_image(self, url: str):
        """下载封面图并返回 PIL Image 对象"""
        safe_url = await self._sanitize_cover_url(url)
        if not safe_url:
            return None
        try:
            session = await self._get_session()
            async with session.get(safe_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                return PILImage.open(io.BytesIO(data))
        except Exception:
            return None

    async def _render_games_local(self, games: list[dict]) -> Comp.Image:
        """使用 Pillow 本地渲染游戏卡片，返回 base64 编码的 Image 组件"""

        fp = self._find_font()
        if not fp:
            raise RuntimeError("未找到可用的 CJK 字体，无法进行本地渲染")

        # --- 缩放与字体 ---
        S = 2  # 2x 高清缩放
        f_header = ImageFont.truetype(fp, 24 * S)
        f_status = ImageFont.truetype(fp, 13 * S)
        f_title = ImageFont.truetype(fp, 18 * S)
        f_desc = ImageFont.truetype(fp, 14 * S)
        f_price = ImageFont.truetype(fp, 14 * S)
        f_footer = ImageFont.truetype(fp, 11 * S)

        # --- 布局常量 ---
        W = 600 * S
        PAD = 24 * S
        GAP = 28 * S
        CPAD = 14 * S
        CRAD = 16 * S
        CW = (W - PAD * 2 - GAP) // 2
        TAW = CW - CPAD * 2
        COV_W = TAW
        COV_H = int(COV_W * 10 / 16)
        COV_RAD = 10 * S

        def _lh(font, extra_px=8):
            bbox = font.getbbox("Ag中")
            return (bbox[3] - bbox[1]) + extra_px * S

        LH_S = _lh(f_status)
        LH_T = _lh(f_title)
        LH_D = _lh(f_desc, 6)
        LH_P = _lh(f_price)

        # --- 颜色 ---
        dark = self.dark_mode
        BG = (23, 26, 33) if dark else (232, 234, 240)
        CARD_BG = (30, 45, 62) if dark else (245, 247, 252)
        HDR_C = (102, 192, 244) if dark else (26, 26, 46)
        TTL_C = (229, 229, 229) if dark else (17, 17, 17)
        DSC_C = (143, 152, 160) if dark else (85, 85, 85)
        FR_C = (102, 187, 106) if dark else (46, 125, 50)
        UP_C = (255, 167, 38) if dark else (230, 81, 0)
        PO_C = (98, 111, 120) if dark else (153, 153, 153)
        FTR_C = (76, 96, 112) if dark else (170, 170, 170)

        # --- 数据清洗（无需 HTML 转义） ---
        cleaned: list[dict] = []
        for game in games:
            raw_desc = str(game.get("description", ""))
            cleaned.append({
                "title": str(game.get("title", "")),
                "description": re.sub(r'\[/?[a-zA-Z0-9]+\]', '', raw_desc),
                "original_price_desc": str(game.get("original_price_desc", "")),
                "free_start": str(game.get("free_start", "")),
                "free_end": str(game.get("free_end", "")),
                "cover_url": game.get("cover", ""),
                "is_free_now": game.get("is_free_now", False),
                "free_start_at": game.get("free_start_at", 0),
            })
        all_games = sorted(cleaned, key=self._game_sort_key)

        # --- 并发下载封面 ---
        cover_imgs: dict[int, PILImage.Image] = {}
        sem = asyncio.Semaphore(5)

        async def _dl(idx: int, url: str):
            async with sem:
                img = await self._download_cover_image(url)
                if img is not None:
                    cover_imgs[idx] = img

        dl_tasks = [_dl(i, g["cover_url"]) for i, g in enumerate(all_games) if g["cover_url"]]
        if dl_tasks:
            await asyncio.gather(*dl_tasks)

        # --- 预计算每张卡片布局 ---
        cards: list[dict] = []
        for i, game in enumerate(all_games):
            if game["is_free_now"]:
                st = f"现在免费，结束日期: {game['free_end']}"
            else:
                st = f"即将推出，{game['free_start']} ~ {game['free_end']}"
            s_lines = _wrap_text(st, f_status, TAW, None)
            t_lines = _wrap_text(game["title"], f_title, TAW, None)
            d_lines = _wrap_text(game["description"], f_desc, TAW, None)
            has_cov = i in cover_imgs

            h = CPAD
            h += len(s_lines) * LH_S + 8 * S
            if has_cov:
                h += COV_H + 10 * S
            h += len(t_lines) * LH_T + 8 * S
            if d_lines:
                h += len(d_lines) * LH_D + 10 * S
            h += LH_P + CPAD

            cards.append({
                "game": game, "s_lines": s_lines, "t_lines": t_lines,
                "d_lines": d_lines, "has_cov": has_cov, "idx": i, "h": h,
            })

        # --- 空状态 ---
        if not cards:
            eh = 300 * S
            img = PILImage.new("RGB", (W, eh), BG)
            draw = ImageDraw.Draw(img)
            hdr = "Epic免费游戏"
            draw.text(((W - f_header.getlength(hdr)) / 2, PAD), hdr, fill=HDR_C, font=f_header)
            hint = "暂无免费游戏数据 🎮"
            draw.text(((W - f_title.getlength(hint)) / 2, eh // 2), hint, fill=DSC_C, font=f_title)
            return self._pil_to_comp_image(img)

        # --- 计算行高与总高 ---
        rows: list[tuple] = []
        for i in range(0, len(cards), 2):
            left = cards[i]
            right = cards[i + 1] if i + 1 < len(cards) else None
            rh = left["h"] if right is None else max(left["h"], right["h"])
            rows.append((left, right, rh))

        hdr_bbox = f_header.getbbox("Ag中")
        hdr_h = hdr_bbox[3] - hdr_bbox[1]
        header_block = PAD + hdr_h + 22 * S

        ftr_bbox = f_footer.getbbox("Ag中")
        ftr_h = ftr_bbox[3] - ftr_bbox[1]
        footer_block = 20 * S + ftr_h + PAD

        grid_h = sum(rh for _, _, rh in rows) + GAP * max(0, len(rows) - 1)
        total_h = header_block + grid_h + footer_block

        # --- 创建画布并绘制 ---
        img = PILImage.new("RGB", (W, total_h), BG)
        draw = ImageDraw.Draw(img)

        # 标题
        hdr = "Epic免费游戏"
        draw.text(((W - f_header.getlength(hdr)) / 2, PAD), hdr, fill=HDR_C, font=f_header)

        y = header_block
        for left, right, row_h in rows:
            for col, cd in enumerate([left, right]):
                if cd is None:
                    continue
                game = cd["game"]
                x = PAD + col * (CW + GAP)

                # 卡片背景（圆角矩形）
                draw.rounded_rectangle(
                    [(x, y), (x + CW, y + row_h)],
                    radius=CRAD, fill=CARD_BG,
                )

                cx = x + CPAD
                cy = y + CPAD

                # 状态文本
                sc = FR_C if game["is_free_now"] else UP_C
                for ln in cd["s_lines"]:
                    draw.text((cx, cy), ln, fill=sc, font=f_status)
                    cy += LH_S
                cy += 8 * S

                # 封面
                if cd["has_cov"]:
                    cov = cover_imgs[cd["idx"]]
                    cov_rgb = cov.convert("RGB").resize((COV_W, COV_H), PILImage.LANCZOS)
                    # 创建圆角蒙版
                    mask = PILImage.new("L", (COV_W, COV_H), 0)
                    ImageDraw.Draw(mask).rounded_rectangle(
                        [(0, 0), (COV_W - 1, COV_H - 1)], radius=COV_RAD, fill=255,
                    )
                    img.paste(cov_rgb, (cx, cy), mask)
                    cov_rgb.close()
                    mask.close()
                    cy += COV_H + 10 * S

                # 标题
                for ln in cd["t_lines"]:
                    draw.text((cx, cy), ln, fill=TTL_C, font=f_title)
                    cy += LH_T
                cy += 8 * S

                # 描述
                for ln in cd["d_lines"]:
                    draw.text((cx, cy), ln, fill=DSC_C, font=f_desc)
                    cy += LH_D
                if cd["d_lines"]:
                    cy += 10 * S

                # 价格
                if game["is_free_now"]:
                    px = cx
                    orig = game["original_price_desc"]
                    if orig and orig != "0":
                        ow = f_price.getlength(orig)
                        draw.text((px, cy), orig, fill=PO_C, font=f_price)
                        # 删除线
                        line_y = cy + LH_P // 2
                        draw.line([(px, line_y), (px + ow, line_y)], fill=PO_C, width=S)
                        px += int(ow) + 8 * S
                    draw.text((px, cy), "免费", fill=FR_C, font=f_price)
                else:
                    draw.text((cx, cy), game["original_price_desc"], fill=UP_C, font=f_price)

            y += row_h + GAP

        # 页脚
        ftr = "Epic Games 周免游戏推送 · by xiaoruange39 · Powered by AstrBot"
        ftr_w = f_footer.getlength(ftr)
        draw.text(((W - ftr_w) / 2, total_h - PAD - ftr_h), ftr, fill=FTR_C, font=f_footer)

        # 清理封面资源
        for cov in cover_imgs.values():
            try:
                cov.close()
            except Exception:
                pass

        return self._pil_to_comp_image(img)

    @staticmethod
    def _pil_to_comp_image(img: "PILImage.Image") -> Comp.Image:
        """将 PIL Image 转换为 base64 编码的 Comp.Image 组件"""
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        img.close()
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return Comp.Image(file=f"base64://{b64}")

    def _format_games_as_text(self, games: list[dict]) -> str:
        """将游戏数据格式化为纯文本，作为渲染失败时的兜底方案"""
        lines = ["🎮 Epic 免费游戏列表", ""]
        for game in games:
            title = game.get("title", "未知游戏")
            is_free = game.get("is_free_now", False)
            start = game.get("free_start", "")
            end = game.get("free_end", "")
            price = game.get("original_price_desc", "免费")
            
            if is_free:
                status = f"✅ 正在免费 (至 {end})"
            else:
                status = f"⏳ 即将推出 ({start} ~ {end})"
            
            lines.append(f"【{title}】")
            lines.append(f"状态: {status}")
            lines.append(f"原价: {price}")
            lines.append("--------------------")
        
        lines.append("Tip: 图片渲染服务稳定后将恢复图片展示。")
        return "\n".join(lines)

    # ==================== 定时任务 ====================

    def _start_cron_task(self):
        """启动 Cron 定时任务"""
        if self._cron_task and not self._cron_task.done():
            self._cron_task.cancel()

        self._cron_task = asyncio.create_task(self._cron_loop())

    async def _cron_loop(self):
        """Cron 循环：调度与重试解耦"""
        try:
            cron = croniter(self.cron_time)
        except (ValueError, KeyError) as e:
            logger.error(f"无效的 Cron 表达式 '{self.cron_time}': {e}")
            return

        max_retries = 5  # 每个调度点最大重试次数

        while True:
            try:
                # === 调度阶段：等待下一个 Cron 时间点 ===
                next_time = cron.get_next(datetime)
                now = datetime.now()
                wait_seconds = (next_time - now).total_seconds()

                if wait_seconds > 0:
                    logger.info(f"Epic 定时推送：下次执行时间 {next_time.strftime('%Y-%m-%d %H:%M:%S')}，等待 {wait_seconds:.0f} 秒")
                    await asyncio.sleep(wait_seconds)

                # === 执行阶段：在当前调度点内重试 ===
                retry_delay = 30  # 初始重试延迟（秒）
                max_retry_delay = 600  # 最大重试延迟（秒）

                for attempt in range(1, max_retries + 1):
                    try:
                        await self._cron_push()
                        break  # 成功，跳出重试循环，推进到下一个 cron 时间
                    except Exception as e:
                        if attempt < max_retries:
                            logger.error(f"Epic 定时推送第 {attempt} 次尝试失败: {e}，{retry_delay} 秒后重试")
                            await asyncio.sleep(retry_delay)
                            retry_delay = min(retry_delay * 2, max_retry_delay)
                        else:
                            logger.error(f"Epic 定时推送第 {attempt} 次尝试失败: {e}，已达最大重试次数，等待下一个调度点")

            except asyncio.CancelledError:
                logger.info("Epic 定时推送任务已取消")
                break
            except Exception as e:
                # cron.get_next() 或其他意外错误
                logger.error(f"Epic 定时推送调度出错: {e}，60 秒后重试")
                await asyncio.sleep(60)

    async def _cron_push(self):
        """定时推送逻辑"""
        # 从配置中获取推送目标，去重
        all_targets = list(dict.fromkeys(self.push_targets))

        if not all_targets:
            logger.info("没有推送目标，跳过 Epic 免费游戏推送")
            return

        try:
            games = await self._fetch_games()
            if not games:
                return

            # 缓存对比（对列表项按稳定键排序后比较，避免仅因顺序变化触发误推送）
            if self.enable_cache:
                last_data = self._load_cache()
                # 按游戏标题和时间组合排序后再序列化，解决同名元素排列不唯一问题
                def _cache_sort_key(g):
                    return f"{g.get('title', '')}_{g.get('free_start_at', 0)}"
                new_data_str = json.dumps(
                    sorted(games, key=_cache_sort_key),
                    ensure_ascii=False, sort_keys=True
                )
                last_data_str = json.dumps(
                    sorted(last_data, key=_cache_sort_key),
                    ensure_ascii=False, sort_keys=True
                ) if last_data else None

                if last_data_str == new_data_str:
                    logger.info("Epic 免费游戏数据未更新，跳过推送")
                    return

            logger.info(f"Epic 免费游戏数据已更新，正在推送到 {len(all_targets)} 个会话...")

            # 渲染消息内容
            rendered = await self._render_games(games)

            # 推送到所有目标（采用并发执行和 Semaphore 限流）
            semaphore = asyncio.Semaphore(5)
            success_count = 0

            async def send_to_target(umo_target: str):
                nonlocal success_count
                async with semaphore:
                    try:
                        msg_chain = MessageChain()
                        if rendered is None:
                            msg_chain.message(self._format_games_as_text(games))
                        else:
                            msg_chain.chain = [rendered]
                        await self.context.send_message(umo_target, msg_chain)
                        success_count += 1
                    except Exception as e:
                        logger.error(f"推送到 {umo_target} 失败: {e}")

            if all_targets:
                tasks = [send_to_target(umo) for umo in all_targets]
                await asyncio.gather(*tasks)

            # 仅在有成功发送时更新缓存，或者本身没有目标配置时（逻辑防空）
            if self.enable_cache:
                if success_count > 0:
                    self._save_cache(games)
                    logger.info("Epic 免费游戏推送完成（已更新缓存）")
                else:
                    logger.warning("所有配置的推送目标均发送失败，本次不更新缓存，等待下个周期重试。")
            else:
                logger.info("Epic 免费游戏推送完成")

        except Exception as e:
            logger.error(f"Epic 定时推送执行出错: {e}")
            raise  # 向上抛出，让 _cron_loop 的指数退避重试机制生效

    # ==================== 持久化 ====================

    def _load_cache(self) -> list | None:
        """加载缓存数据"""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"读取缓存失败: {e}")
        return None

    def _save_cache(self, data: list):
        """保存缓存数据"""
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")

    # ==================== 生命周期 ====================

    async def terminate(self):
        """插件卸载/停用时调用"""
        if self._cron_task and not self._cron_task.done():
            self._cron_task.cancel()
            try:
                await self._cron_task
            except asyncio.CancelledError:
                pass

        # 关闭共享 HTTP 会话
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

        logger.info("Epic 免费游戏插件已停用")
