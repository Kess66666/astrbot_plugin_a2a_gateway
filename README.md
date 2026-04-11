# A2A Gateway Plugin

基于 **A2A (Agent-to-Agent)** 协议的跨 Agent 通信网关插件，专为 AstrBot 设计。

## 功能特性

- 🔗 **多节点管理** - 添加、查看、删除远程 A2A Agent
- 📤 **消息路由** - 向指定节点发送消息并获取响应
- 📋 **任务追踪** - 记录每次通信的任务状态和结果
- 💾 **持久化存储** - 节点配置自动保存到本地
- 🛡️ **故障容错** - 节点失败自动计数，连续失败过多自动禁用

## 指令列表

| 指令 | 说明 |
|------|------|
| `/a2a` | 显示帮助菜单 |
| `/a2a-list` | 查看已配置的节点列表 |
| `/a2a-add <名称> <AgentCard URL> [Token]` | 添加新节点 |
| `/a2a-remove <名称>` | 删除指定节点 |
| `/a2a-send <节点名> <消息>` | 向节点发送消息 |
| `/a2a-status` | 查看系统状态统计 |
| `/a2a-tasks` | 查看最近任务记录 |

## 快速开始

### 1. 安装

将插件目录克隆到 AstrBot 插件目录：

```bash
cd /AstrBot/data/plugins
git clone https://github.com/Kess66666/astrbot_plugin_a2a_gateway.git
```

### 2. 添加节点

```bash
/a2a-add my-agent https://remote-agent.com/agent.json
```

### 3. 发送消息

```bash
/a2a-send my-agent 你好，请介绍一下自己
```

## A2A 协议说明

本插件实现简化版 A2A 协议，支持：

- **Agent Card 发现** - 通过 `.well-known/agent.json` 获取 Agent 元信息
- **JSON-RPC 2.0** - 使用标准 JSON-RPC 格式通信
- **Bearer Token** - 可选的 Bearer Token 认证

## 配置选项

在 Web 管理面板中可配置：

| 选项 | 默认值 | 说明 |
|------|--------|------|
| timeout | 30.0 | 请求超时时间（秒） |

## 存储位置

- 节点配置: `/AstrBot/data/plugins_data/a2a_gateway/peers.json`
- 错误日志: `/AstrBot/data/learnings/`

## License

MIT
