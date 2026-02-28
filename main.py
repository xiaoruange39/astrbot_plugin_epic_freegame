import asyncio
import json
import os
import html
from datetime import datetime

import aiohttp
from croniter import croniter

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.event import MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig


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
    width: 660px;
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
    box-shadow:
      0 2px 16px rgba(0, 0, 0, 0.06),
      0 8px 32px rgba(0, 0, 0, 0.04),
      inset 0 1px 0 rgba(255, 255, 255, 0.8);
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

  /* ========== 深色模式 ========== */
  body.dark {
    background: linear-gradient(145deg, #0c0e1a, #141829, #1a1e35);
    color: #d0d0d0;
  }

  body.dark .header h1 {
    color: #5cf;
  }

  body.dark .game-card {
    background: rgba(100, 120, 180, 0.08);
    border: 1px solid rgba(120, 150, 220, 0.15);
    border-top: 1px solid rgba(140, 170, 240, 0.25);
    box-shadow:
      0 2px 20px rgba(0, 0, 0, 0.4),
      0 8px 40px rgba(0, 0, 0, 0.2),
      inset 0 1px 0 rgba(160, 180, 255, 0.1);
  }

  body.dark .game-status.free { color: #66bb6a; }
  body.dark .game-status.upcoming { color: #ffa726; }
  body.dark .game-title { color: #eee; }
  body.dark .game-desc { color: #9aa; }
  body.dark .price-original { color: #667; }
  body.dark .price-current-free { color: #66bb6a; }
  body.dark .price-current-upcoming { color: #ffa726; }
  body.dark .footer { color: #445; }
  body.dark .empty-hint { color: #556; }

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
    gap: 20px;
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

      <img class="game-cover" src="{{ game.cover }}" alt="cover" />

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


@register(
    "astrbot_plugin_epic_freegame",
    "xxmod",
    "Epic 每周免费游戏推送，支持定时推送和手动查询",
    "1.0.0",
    "https://github.com/xxmod/astrbot_plugin_epic_freegame"
)
class EpicFreeGamePlugin(Star):
    """Epic Games 每周免费游戏推送插件

    功能：
    1. /epic 指令：手动查询当前 Epic 免费游戏
    2. 定时推送：根据 Cron 表达式自动推送到已订阅的会话
    3. /epic_sub 指令：订阅定时推送
    4. /epic_unsub 指令：取消订阅
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

        # 从配置中读取推送目标列表
        push_targets_raw = config.get("push_targets", [])
        if isinstance(push_targets_raw, list):
            self.push_targets: list[str] = [t.strip() for t in push_targets_raw if isinstance(t, str) and t.strip()]
        else:
            self.push_targets: list[str] = []

        # 数据目录（持久化数据应存储于 data 目录下）
        self.data_dir = os.path.join("data", "astrbot_plugin_epic_freegame")
        os.makedirs(self.data_dir, exist_ok=True)

        # 缓存文件路径
        self.cache_path = os.path.join(self.data_dir, "epic_free_cache.json")
        # 订阅列表文件路径
        self.sub_path = os.path.join(self.data_dir, "subscriptions.json")

        # 订阅列表（存储 unified_msg_origin）
        self.subscriptions: list[str] = self._load_subscriptions()

        # 定时任务句柄
        self._cron_task: asyncio.Task | None = None

    async def initialize(self):
        """插件初始化，启动定时任务"""
        if self.cron_time:
            self._start_cron_task()
            logger.info(f"Epic 免费游戏定时推送已启动，Cron: {self.cron_time}")
        else:
            logger.info("未配置 Cron 表达式，Epic 免费游戏定时推送未启用")

    # ==================== 指令 ====================

    @filter.command("epic")
    async def cmd_epic(self, event: AstrMessageEvent):
        '''查询当前 Epic 免费游戏'''
        yield event.plain_result("正在获取 Epic 免费游戏信息，请稍候... 🎮")

        try:
            games = await self._fetch_games()
            if not games:
                yield event.plain_result("未获取到任何游戏数据 😢")
                return

            # 渲染为图片
            image_url = await self._render_games(games)
            yield event.image_result(image_url)

        except Exception as e:
            logger.error(f"获取 Epic 免费游戏信息失败: {e}")
            yield event.plain_result(f"获取 Epic 免费游戏信息失败，请稍后重试 😢\n错误: {e}")

    @filter.command("epic_sub")
    async def cmd_subscribe(self, event: AstrMessageEvent):
        '''订阅 Epic 免费游戏定时推送'''
        umo = event.unified_msg_origin

        if umo in self.subscriptions:
            yield event.plain_result("当前会话已订阅 Epic 免费游戏推送 ✅")
            return

        self.subscriptions.append(umo)
        self._save_subscriptions()
        yield event.plain_result("订阅成功！将在定时任务触发时自动推送 Epic 免费游戏信息 🎮✅")

    @filter.command("epic_unsub")
    async def cmd_unsubscribe(self, event: AstrMessageEvent):
        '''取消订阅 Epic 免费游戏定时推送'''
        umo = event.unified_msg_origin

        if umo not in self.subscriptions:
            yield event.plain_result("当前会话未订阅 Epic 免费游戏推送 ❌")
            return

        self.subscriptions.remove(umo)
        self._save_subscriptions()
        yield event.plain_result("已取消订阅 Epic 免费游戏推送 ❎")

    # ==================== 核心逻辑 ====================

    async def _fetch_games(self) -> list[dict] | None:
        """从 API 获取 Epic 免费游戏数据"""
        if not self.api_url:
            logger.warning("未配置 API 地址")
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.error(f"API 请求失败，状态码: {resp.status}")
                        return None
                    data = await resp.json()
        except Exception as e:
            logger.error(f"拉取 Epic 免费游戏信息失败: {e}")
            raise

        games = data if isinstance(data, list) else data.get("data", [])

        if not games:
            logger.info("未获取到任何游戏数据")
            return None

        return games

    async def _render_games(self, games: list[dict]) -> str:
        """将游戏数据渲染为图片，返回图片 URL"""
        # 转义 HTML 特殊字符
        for game in games:
            game["title"] = html.escape(game.get("title", ""))
            game["description"] = html.escape(game.get("description", ""))

        # 正在免费的排前面，即将免费的排后面
        all_games = sorted(games, key=lambda g: (not g.get("is_free_now"), g.get("free_start_at", 0)))

        update_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        render_data = {
            "all_games": all_games,
            "update_time": update_time,
            "theme": "dark" if self.dark_mode else "light",
        }

        options = {
            "full_page": True,
            "viewport_width": 660,
            "device_scale_factor_level": "ultra",
        }

        image_url = await self.html_render(
            HTML_TEMPLATE,
            render_data,
            options=options,
        )
        return image_url

    # ==================== 定时任务 ====================

    def _start_cron_task(self):
        """启动 Cron 定时任务"""
        if self._cron_task and not self._cron_task.done():
            self._cron_task.cancel()

        self._cron_task = asyncio.create_task(self._cron_loop())

    async def _cron_loop(self):
        """Cron 循环"""
        try:
            cron = croniter(self.cron_time)
        except (ValueError, KeyError) as e:
            logger.error(f"无效的 Cron 表达式 '{self.cron_time}': {e}")
            return

        while True:
            try:
                next_time = cron.get_next(datetime)
                now = datetime.now()
                wait_seconds = (next_time - now).total_seconds()

                if wait_seconds > 0:
                    logger.info(f"Epic 定时推送：下次执行时间 {next_time.strftime('%Y-%m-%d %H:%M:%S')}，等待 {wait_seconds:.0f} 秒")
                    await asyncio.sleep(wait_seconds)

                await self._cron_push()

            except asyncio.CancelledError:
                logger.info("Epic 定时推送任务已取消")
                break
            except Exception as e:
                logger.error(f"Epic 定时推送任务执行出错: {e}")
                # 出错后等待 60 秒再重试
                await asyncio.sleep(60)

    async def _cron_push(self):
        """定时推送逻辑"""
        # 合并配置中的推送目标和指令订阅的目标，去重
        all_targets = list(dict.fromkeys(self.push_targets + self.subscriptions))

        if not all_targets:
            logger.info("没有推送目标，跳过 Epic 免费游戏推送")
            return

        try:
            games = await self._fetch_games()
            if not games:
                return

            # 缓存对比
            if self.enable_cache:
                last_data = self._load_cache()
                new_data_str = json.dumps(games, ensure_ascii=False, sort_keys=True)
                last_data_str = json.dumps(last_data, ensure_ascii=False, sort_keys=True) if last_data else None

                if last_data_str == new_data_str:
                    logger.info("Epic 免费游戏数据未更新，跳过推送")
                    return

            logger.info(f"Epic 免费游戏数据已更新，正在推送到 {len(all_targets)} 个会话...")

            # 渲染图片
            image_url = await self._render_games(games)

            # 推送到所有目标
            for umo in all_targets:
                try:
                    chain = MessageChain().image(image_url)
                    await self.context.send_message(umo, chain)
                except Exception as e:
                    logger.error(f"推送到 {umo} 失败: {e}")

            # 更新缓存
            if self.enable_cache:
                self._save_cache(games)

            logger.info("Epic 免费游戏推送完成")

        except Exception as e:
            logger.error(f"Epic 定时推送执行出错: {e}")

    # ==================== 持久化 ====================

    def _load_subscriptions(self) -> list[str]:
        """加载订阅列表"""
        if os.path.exists(self.sub_path):
            try:
                with open(self.sub_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
            except Exception as e:
                logger.warning(f"读取订阅列表失败: {e}")
        return []

    def _save_subscriptions(self):
        """保存订阅列表"""
        try:
            with open(self.sub_path, "w", encoding="utf-8") as f:
                json.dump(self.subscriptions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存订阅列表失败: {e}")

    def _load_cache(self) -> list | None:
        """加载缓存数据"""
        if os.path.exists(self.cache_path):
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
        logger.info("Epic 免费游戏插件已停用")
