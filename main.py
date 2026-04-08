import asyncio
import re
import copy
import json
import html
import shutil
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


# ==================== HTML 模板 ====================

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: "Microsoft YaHei", "PingFang SC", "Helvetica Neue", sans-serif;
    padding: 24px;
    width: 600px;
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
    grid-template-columns: 1fr 1fr;
    gap: 28px;
  }

  /* 液态玻璃卡片 */
  .game-card {
    border-radius: 16px;
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
  }

  .game-desc {
    font-size: 14px;
    line-height: 1.7;
    margin-bottom: 10px;
  }

  .game-price {
    font-size: 14px;
    display: flex;
    align-items: center;
    gap: 8px;
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
</style>
</head>
<body class="{{ theme }}">
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
                # 尝试渲染为图片（返回插件数据目录下的本地文件路径）
                image_path = await self._render_games(games)
                yield event.chain_result([Comp.Image.fromFileSystem(image_path)])
            except Exception as render_err:
                logger.warning(f"Epic 免费游戏图片渲染失败，切换为文本模式: {render_err}")
                text_result = self._format_games_as_text(games)
                yield event.plain_result(f"【⚠️ 渲染服务器忙，已为你切换为文本模式】\n\n{text_result}")

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

    def _cleanup_old_renders(self):
        """清理插件数据目录中旧的渲染临时图片"""
        try:
            for f in self.data_dir.glob("epic_render_*"):
                try:
                    f.unlink()
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"清理旧渲染图片失败: {e}")

    async def _render_games(self, games: list[dict]) -> str:
        """将游戏数据渲染为图片，返回图片本地路径（保存在插件数据目录下）"""
        # 深拷贝以避免污染原始数据（缓存对比需要未转义的原始数据）
        render_games = copy.deepcopy(games)

        # 转义所有文本字段（仅在拷贝上操作），防止 HTML/属性 注入
        for game in render_games:
            game["title"] = html.escape(str(game.get("title", "")))
            # 清除 BBCode 标签（如 [b]...[/b]）
            raw_desc = str(game.get("description", ""))
            clean_desc = re.sub(r'\[/?[a-zA-Z0-9]+\]', '', raw_desc)
            game["description"] = html.escape(clean_desc)
            game["original_price_desc"] = html.escape(str(game.get("original_price_desc", "")))
            game["free_start"] = html.escape(str(game.get("free_start", "")))
            game["free_end"] = html.escape(str(game.get("free_end", "")))
            # 校验封面图 URL 并做引号转义，防止属性逃逸 SSRF+XSS
            safe_cover = await self._sanitize_cover_url(game.get("cover", ""))
            game["cover"] = html.escape(safe_cover, quote=True)

        # 正在免费的排前面，即将免费的排后面（类型归一化避免 TypeError）
        def _sort_key(g):
            free_start = g.get("free_start_at", 0)
            # 统一转为数值时间戳，支持 int、ISO 8601 字符串、None 等多种类型
            if free_start is None:
                return (not g.get("is_free_now", False), 0)
            try:
                # 尝试直接转 int（Unix 时间戳）
                return (not g.get("is_free_now", False), int(free_start))
            except (ValueError, TypeError):
                pass
            try:
                # 尝试解析 ISO 8601 格式（如 "2023-10-12T15:00:00.000Z"）
                dt_str = str(free_start).replace("Z", "+00:00")
                dt = datetime.fromisoformat(dt_str)
                return (not g.get("is_free_now", False), int(dt.timestamp()))
            except (ValueError, TypeError):
                pass
            return (not g.get("is_free_now", False), 0)

        all_games = sorted(render_games, key=_sort_key)

        render_data = {
            "all_games": all_games,
            "theme": "dark" if self.dark_mode else "light",
        }

        options = {
            "full_page": True,
            "viewport_width": 600,
            "device_scale_factor_level": "ultra",
        }

        # 清理上一次的渲染临时图片
        self._cleanup_old_renders()

        # 使用 return_url=False 获取本地文件路径
        raw_path = await self.html_render(
            HTML_TEMPLATE,
            render_data,
            return_url=False,
            options=options,
        )

        # 将渲染结果迁移到插件专属数据目录，规范化临时文件存储位置
        raw_file = Path(raw_path)
        suffix = raw_file.suffix or ".png"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_path = self.data_dir / f"epic_render_{timestamp}{suffix}"
        try:
            shutil.move(str(raw_file), str(dest_path))
        except Exception:
            # move 失败时尝试 copy + 删除源文件
            shutil.copy2(str(raw_file), str(dest_path))
            try:
                raw_file.unlink()
            except Exception:
                pass

        return str(dest_path)

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

            # 渲染图片（返回插件数据目录下的本地文件路径）
            image_path = await self._render_games(games)

            # 推送到所有目标（采用并发执行和 Semaphore 限流）
            semaphore = asyncio.Semaphore(5)
            success_count = 0

            async def send_to_target(umo_target: str):
                nonlocal success_count
                async with semaphore:
                    try:
                        # 使用官方 Comp.Image.fromFileSystem 发送本地图片
                        chain = [Comp.Image.fromFileSystem(image_path)]
                        await self.context.send_message(umo_target, chain)
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
