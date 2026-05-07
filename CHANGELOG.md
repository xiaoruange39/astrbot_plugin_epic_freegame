# Changelog

All notable changes to this project will be documented in this file.

## [v1.0.8] - 2026-05-07

### Fixed
- 修复了定时推送在纯文字模式下发送 `None` 的问题。
- 优化了本地渲染的文本换行，避免标题和描述被过早省略。

## [v1.0.7] - 2026-05-04

### Fixed
- 修复了定时推送报错 `'list' object has no attribute 'chain'` 导致推送失败的问题（适配了 AstrBot 最新的消息发送链 `MessageChain`）。

## [v1.0.6] - 2026-05-04

### Added
- 初始化发布：获取 Epic 每周免费游戏信息。
- 支持指令查询与定时推送功能。
- 支持使用 60s API 获取数据并渲染为图片发送。
