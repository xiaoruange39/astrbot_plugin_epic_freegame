![:name](https://count.getloli.com/@astrbot_plugin_epic_freegame?name=astrbot_plugin_epic_freegame&theme=green&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto&prefix=0)

# 🎮 astrbot_plugin_epic_freegame

> Epic Games 每周免费游戏推送插件（AstrBot 版）

通过 [60s API](https://60s.viki.moe/) 获取 Epic 每周免费游戏信息，渲染为精美卡片图片并推送到群聊，支持深色 / 浅色双主题。

## ✨ 功能

- 📋 **手动查询** — 发送 `/epic` 即可查看当前 Epic 免费游戏
- 🔔 **定时推送** — 支持 Cron 表达式，自动定时推送到指定群聊
- 🎯 **白名单推送** — 可在 WebUI 中直接配置推送目标群组
- 🖼️ **高清图片渲染** — 游戏信息渲染为超高清卡片图（Ultra 分辨率）
- 🌗 **深色 / 浅色主题** — 一键切换
- 💾 **智能缓存** — 对比缓存数据，仅在内容更新时推送，避免重复打扰

## 📦 安装

在 AstrBot WebUI 插件市场中搜索 `astrbot_plugin_epic_freegame` 安装，或通过仓库地址安装：

```
https://github.com/xiaoruange39/astrbot_plugin_epic_freegame
```

### 依赖

插件依赖以下 Python 包（会自动安装）：

- `aiohttp` — HTTP 请求
- `croniter` — Cron 表达式解析

## ⚙️ 配置说明

安装后在 AstrBot WebUI 的插件配置页面中进行设置：

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `api_url` | string | Epic 免费游戏 API 地址 | `https://60s.viki.moe/v2/epic` |
| `cron_time` | string | 定时推送 Cron 表达式，为空则不启用 | 空 |
| `enable_cache` | bool | 启用缓存对比，避免重复推送 | `true` |
| `dark_mode` | bool | 深色模式开关 | `true` |
| `push_targets` | list | 白名单群组 UMO 列表 | `[]` |

### 🕐 Cron 表达式示例

| 表达式 | 含义 |
|--------|------|
| `0 10 * * *` | 每天 10:00 推送 |
| `0 10 * * 5` | 每周五 10:00 推送 |
| `0 10,20 * * *` | 每天 10:00 和 20:00 推送 |
| `0 12 * * 1,4` | 每周一、周四 12:00 推送 |

### 🎯 推送目标配置

**WebUI 配置（推荐）**

在 `push_targets`（白名单群组 UMO 列表）中添加目标群组的 UMO。

> 💡 **如何获取 UMO？** 在目标群聊中发送 `/sid`，即可获取该群的完整 UMO。

## 📖 指令列表

| 指令 | 说明 |
|------|------|
| `/epic` | 查询当前 Epic 免费游戏，渲染为图片发送 |

## 🎨 主题预览

插件内置两套主题：

- **深色模式** — 深蓝紫色调背景，青蓝色标题，半透明蓝紫玻璃卡片
- **浅色模式** — 浅灰蓝渐变背景，白色半透明毛玻璃卡片

通过 WebUI 中的 `dark_mode` 开关一键切换。

## 📝 更新日志

### v1.0.0

- 从 Koishi 插件迁移至 AstrBot 平台
- 使用 AstrBot 内置 HTML 渲染，超高清输出
- 深色 / 浅色双主题切换
- 新增白名单群组 UMO 配置
- 新增订阅管理功能
- 智能缓存，避免重复推送

## 📄 License

MIT

## 👤 作者

- **xiaoruange39**
- **[欢迎进群玩](https://qm.qq.com/q/8kdJ2Bzf6S)**
