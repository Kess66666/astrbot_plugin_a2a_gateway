# A2A Gateway Plugin

基于 **A2A (Agent-to-Agent)** 协议的跨 Agent 通信网关插件，专为 AstrBot 设计。

> **当前版本: v1.3.4** (适配 AstrBot v4.22.3，使用 `llm_generate` 替代 `post_event`)

## 功能特性

- 🔗 **多节点管理** - 添加、查看、删除远程 A2A Agent
- 📤 **消息路由** - 向指定节点发送消息并获取响应
- 📋 **任务追踪** - 记录每次通信的任务状态和结果
- 💾 **持久化存储** - 节点配置自动保存到本地
- 🛡️ **故障容错** - 节点失败自动计数，连续失败过多自动禁用
- 🖥️ **服务端支持** - 暴露 A2A Web 端点，接收并处理来自其他 Agent 的请求
- 🔐 **安全鉴权** - Bearer Token 认证，确保 A2A 通信安全

## 模式说明

### 客户端模式 (Client)
作为 A2A 客户端，向其他 Agent 发起请求。

### 服务端模式 (Server)
作为 A2A 服务端，接收其他 Agent 的请求并响应。

```
    ┌──────────────┐         A2A          ┌──────────────┐
    │  AstrBot A   │ ── /a2a-send ──→    │  AstrBot B   │
    │  (Client)    │ ←── response ──     │  (Server)    │
    └──────────────┘                     └──────────────┘
           ↓                                   ↓
    /api/plug/astrbot_plugin_a2a_gateway   (根路径兼容)
    Authorization: Bearer <token>        Authorization: Bearer <token>
```

## 指令列表

| 指令 | 说明 |
|------|------|
| `/a2a` | 显示帮助菜单 |
| `/a2a_list` | 查看已配置的节点列表 |
| `/a2a_add <名称> <AgentCard URL> [Token]` | 添加新节点 |
| `/a2a_remove <名称>` | 删除指定节点 |
| `/a2a_send <节点名> <消息>` | 向节点发送消息 |
| `/a2a_status` | 查看系统状态统计 |
| `/a2a_tasks` | 查看最近任务记录 |
| `/a2a_token` | 查看/重置 A2A 鉴权 Token |
| `/a2a_token reset` | 重置 A2A 鉴权 Token |
| `/a2a_force_reg` | 强制重新注册 Web 路由 |

## 快速开始

### 1. 安装

```bash
cd /AstrBot/data/plugins
git clone https://github.com/Kess66666/astrbot_plugin_a2a_gateway.git
```

### 2. 配置服务端 Token

在 Web 管理面板中设置 `a2a_token`（建议使用强密码）。

查看当前 Token：
```bash
/a2a_token
```

### 3. 添加节点

```bash
/a2a_add my-agent http://192.168.1.100:6185/api/plug/astrbot_plugin_a2a_gateway/agent.json your_token
```

### 4. 发送消息

```bash
/a2a_send my-agent 你好，请介绍一下自己
```

## 服务端接口

### GET /api/plug/astrbot_plugin_a2a_gateway/agent.json
返回 Agent Card（AID 协议），包含 Agent 元信息。

**请求示例：**
```bash
curl -H "Authorization: Bearer <your_token>" \
     http://your-bot:6185/api/plug/astrbot_plugin_a2a_gateway/agent.json
```

### POST /api/plug/astrbot_plugin_a2a_gateway (根路径)
处理 A2A JSON-RPC 消息（兼容模式）。

**请求示例：**
```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your_token>" \
  -d '{
    "jsonrpc": "2.0",
    "id": "msg-001",
    "method": "message",
    "params": {
      "message": {
        "role": "user",
        "content": "你好，请介绍一下自己"
      }
    }
  }' \
  http://your-bot:6185/api/plug/astrbot_plugin_a2a_gateway
```

**响应示例：**
```json
{
  "jsonrpc": "2.0",
  "id": "msg-001",
  "result": {
    "content": [
      {"type": "text", "text": "我是基于 AstrBot 的 A2A Agent..."}
    ]
  }
}
```

## 版本更新日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.3.4 | 2026-04-13 | ✅ 使用 `llm_generate` 替代废弃的 `post_event`<br>✅ 根路径 POST 兼容<br>✅ 移除 `FakeEvent` 注入逻辑 |
| v1.3.2 | 2026-04-12 | 路由注册修复，版本号对齐 |
| v1.0.0 | - | 初始版本 |

## A2A 协议说明

本插件实现完整 A2A 协议，支持：

- **Agent Card 发现** - 通过 `/agent.json` 获取 Agent 元信息
- **JSON-RPC 2.0** - 使用标准 JSON-RPC 格式通信
- **Bearer Token** - Bearer Token 认证（必填）
- **直接 LLM 调用** - 服务端使用 `context.llm_generate` 直接获取 AI 回复

## 配置选项

在 Web 管理面板中可配置：

| 选项 | 默认值 | 说明 |
|------|--------|------|
| timeout | 30.0 | 请求超时时间（秒） |
| a2a_token | (自动生成) | A2A 服务端鉴权 Token |
| agent_name | AstrBot-A2A | Agent 名称 |
| agent_description | ... | Agent 描述 |
| auto_register | true | 自动注册 Web 路由 |

## 存储位置

- 节点配置: `/AstrBot/data/plugins_data/a2a_gateway/peers.json`
- 错误日志: `/AstrBot/data/learnings/`

## License

MIT
