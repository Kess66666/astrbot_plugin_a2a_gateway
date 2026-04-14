# 📡 AstrBot A2A Gateway 插件

实现 Agent-to-Agent (A2A) 协议的网关插件，支持多实例互联、JSON-RPC 通信、Token 鉴权。

## ✨ v1.4.0 新功能：记忆同步拦截器 🕊️

内置 **Memory Sync Interceptor**，可识别并拦截 Door 发来的 `SYSTEM_SYNC` 消息，直接写入本地 `learnings/` 目录，**零 LLM 调用、零延迟、零成本**！

### 配置项

```yaml
# 启用记忆同步拦截（默认开启）
memory_sync_enabled: true

# 记忆归档目录（默认路径）
memory_sync_dir: "/AstrBot/data/learnings/"
```

### 工作原理

```
Door 发送 ──HTTP POST──▶ A2A Gateway
                              │
                    ┌─────────┴──────────┐
                    │ 检查消息标记        │
                    │ SYSTEM_SYNC?        │
                    └────┬───────────┬────┘
                         │           │
                       ✅是         ❌否
                         │           │
                   直接归档到       调用 LLM
                   learnings/       处理回复
                   返回 JSON-RPC    
                   成功响应         
```

## 📦 安装

1. 克隆或下载本插件到 `data/plugins/astrbot_plugin_a2a_gateway/`
2. 在 AstrBot 面板中配置节点和 Token
3. 重启 AstrBot 或使用 `/a2a_force_reg` 注册路由

## 🔧 指令

- `/a2a` - 查看主菜单和状态
- `/a2a_list` - 查看已注册节点
- `/a2a_add <名称> <URL> [token]` - 添加节点
- `/a2a_remove <名称>` - 删除节点
- `/a2a_send <节点名> <消息>` - 发送消息
- `/a2a_status` - 查看系统状态
- `/a2a_token` - 查看/重置 Token
- `/a2a_force_reg` - 强制重新注册路由

## 🤝 配套插件

本插件可与 [Memory Sync Bridge](https://github.com/Kess66666/astrbot-plugin-memory-sync) 配合使用，实现跨实例记忆自动同步。

## 📝 更新日志

### v1.4.0 (2026-04-14)
- 🕊️ 新增 Memory Sync Interceptor，拦截同步消息直接归档
- 💰 零 LLM 调用，零延迟处理记忆同步
- ⚙️ 支持配置 `memory_sync_enabled` 和 `memory_sync_dir`
- 🐛 修复 `cmd_list` 语法错误

### v1.3.9 (2026-04-13)
- ✅ 优先从 config.json 读取 Token
- ✅ 修复路由注册问题
- ✅ 完善错误处理和日志

## 📄 License

MIT
