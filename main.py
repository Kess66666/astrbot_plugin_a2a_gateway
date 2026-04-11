import json, uuid, httpx, os, hashlib, secrets
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from datetime import datetime
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent, Bus as EventBus
from astrbot.api.star import Context, Star
from astrbot.api.message_components import Plain

@dataclass
class Peer:
    name: str
    agent_card_url: str
    base_url: str
    auth_type: str = ""
    token: str = ""
    skills: List[str] = field(default_factory=list)
    enabled: bool = True
    failure_count: int = 0
    created_at: str = ""

@dataclass
class Task:
    task_id: str
    peer_name: str
    status: str  # pending, running, completed, failed
    created_at: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class A2AClient:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def get_agent_card(self, url: str, auth_type: str = "", token: str = "") -> Dict[str, Any]:
        """获取 Agent Card (AID 协议)"""
        headers = {}
        if auth_type in ("bearer", "apiKey") and token:
            headers["Authorization"] = f"Bearer {token}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def send_message(
        self, 
        base_url: str, 
        message: Dict[str, Any],
        auth_type: str = "", 
        token: str = ""
    ) -> Dict[str, Any]:
        """发送消息到远程 A2A Agent"""
        headers = {"Content-Type": "application/json"}
        if auth_type in ("bearer", "apiKey") and token:
            headers["Authorization"] = f"Bearer {token}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(base_url, json=message, headers=headers)
            resp.raise_for_status()
            return resp.json()


class A2AGatewayPlugin(Star):
    def __init__(self, context=None, config=None, **kwargs):
        super().__init__(context)
        # 兼容模式：处理 context 被当作 config 传入的情况
        if context is not None and not hasattr(context, 'get_plugin_data_dir'):
            if config is None:
                config = context
            context = None
        self.context = context
        self.config = config if isinstance(config, dict) else {}
        self.client = A2AClient(timeout=self.config.get("timeout", 30.0))
        self.peers: Dict[str, Peer] = {}
        self.tasks: Dict[str, Task] = {}
        self._storage_path = self._get_storage_path()
        self._event_bus: Optional[EventBus] = None
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._load_peers()
        logger.info("[A2A Gateway] 插件初始化完成 (v1.1.0 Client+Server)")

    def _get_storage_path(self) -> str:
        """获取存储路径"""
        if self.context and hasattr(self.context, 'get_plugin_data_dir'):
            return self.context.get_plugin_data_dir()
        return "/AstrBot/data/plugins_data/a2a_gateway"

    def _load_peers(self):
        """从磁盘加载 peers 配置"""
        os.makedirs(self._storage_path, exist_ok=True)
        peers_file = os.path.join(self._storage_path, "peers.json")
        if os.path.exists(peers_file):
            try:
                with open(peers_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for name, pdata in data.items():
                        self.peers[name] = Peer(**pdata)
                logger.info(f"[A2A Gateway] 已加载 {len(self.peers)} 个节点")
            except Exception as e:
                logger.error(f"[A2A Gateway] 加载 peers 失败: {e}")

    def _save_peers(self):
        """保存 peers 到磁盘"""
        peers_file = os.path.join(self._storage_path, "peers.json")
        data = {name: asdict(p) for name, p in self.peers.items()}
        with open(peers_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    async def init(self, *args, **kwargs):
        """插件初始化"""
        import asyncio
        # 尝试获取事件总线用于内部通信
        if self.context and hasattr(self.context, 'event_bus'):
            self._event_bus = self.context.event_bus
            logger.info("[A2A Gateway] 事件总线已绑定")
        
        # 获取配置的 token
        self._a2a_token = self.config.get("a2a_token", "")
        self._agent_name = self.config.get("agent_name", "AstrBot-A2A")
        self._agent_desc = self.config.get("agent_description", "AstrBot powered A2A Agent")
        
        # 如果没有设置 token，自动生成一个
        if not self._a2a_token:
            self._a2a_token = secrets.token_urlsafe(32)
            logger.warning(f"[A2A Gateway] 未设置 A2A Token，已自动生成: {self._a2a_token[:8]}...")
            logger.warning("[A2A Gateway] 请在配置中设置 a2a_token 以确保安全!")
        
        logger.info(f"[A2A Gateway] 服务端模式就绪，Token: {self._a2a_token[:8]}...")

    # ==================== Web 路由 (服务端) ====================
    
    @Star.route("/agent.json")
    async def serve_agent_card(self, request):
        """提供 Agent Card (A2A 协议)"""
        # 安全检查
        auth_ok, error_msg = await self._check_auth(request)
        if not auth_ok:
            return {"status": 401, "body": json.dumps({"error": error_msg})}
        
        agent_card = {
            "name": self._agent_name,
            "description": self._agent_desc,
            "version": "1.0.0",
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "stateTransitions": False
            },
            "skills": [
                {
                    "id": "general-chat",
                    "name": "General Chat",
                    "description": "通用对话能力，通过 A2A 协议接收消息"
                }
            ],
            "url": f"/api/a2a/proxy"
        }
        return {"status": 200, "body": json.dumps(agent_card)}

    @Star.route("/api/a2a/proxy", methods=["POST"])
    async def handle_a2a_message(self, request):
        """处理 A2A JSON-RPC 消息"""
        import asyncio
        
        # 安全鉴权
        auth_ok, error_msg = await self._check_auth(request)
        if not auth_ok:
            return {"status": 401, "body": json.dumps({"jsonrpc": "2.0", "error": {"code": -32600, "message": error_msg}})}
        
        try:
            # 解析 JSON-RPC 请求
            body = json.loads(request.get("body", "{}"))
            
            jsonrpc = body.get("jsonrpc")
            method = body.get("method")
            msg_id = body.get("id")
            params = body.get("params", {})
            
            if jsonrpc != "2.0":
                return {"status": 400, "body": json.dumps({
                    "jsonrpc": "2.0", 
                    "error": {"code": -32600, "message": "Invalid Request: jsonrpc must be 2.0"}
                })}
            
            if method == "message":
                # 提取消息内容
                message_data = params.get("message", {})
                content = message_data.get("content", "")
                role = message_data.get("role", "user")
                
                logger.info(f"[A2A Gateway] 收到消息 from {role}: {content[:100]}...")
                
                # 创建 Future 用于等待响应
                future = asyncio.Future()
                self._pending_requests[str(msg_id)] = future
                
                try:
                    # 通过事件总线注入消息（如果可用）
                    if self._event_bus:
                        await self._inject_message(content, msg_id, future)
                        
                        # 等待处理结果（带超时）
                        try:
                            response_text = await asyncio.wait_for(future, timeout=self.config.get("timeout", 30.0))
                        except asyncio.TimeoutError:
                            response_text = "处理超时，请重试"
                    else:
                        # 降级：无事件总线，直接返回
                        response_text = "服务端已收到消息，但事件总线未就绪"
                    
                    # 返回 A2A 响应
                    return {"status": 200, "body": json.dumps({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {"type": "text", "text": response_text}
                            ]
                        }
                    })}
                    
                finally:
                    self._pending_requests.pop(str(msg_id), None)
                    
            elif method == "tasks/cancel":
                # 取消任务（简化实现）
                return {"status": 200, "body": json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"ok": True}
                })}
            else:
                return {"status": 400, "body": json.dumps({
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })}
                
        except json.JSONDecodeError:
            return {"status": 400, "body": json.dumps({
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"}
            })}
        except Exception as e:
            logger.error(f"[A2A Gateway] 处理请求失败: {e}")
            return {"status": 500, "body": json.dumps({
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": f"Internal error: {str(e)}"}
            })}

    async def _check_auth(self, request) -> tuple[bool, str]:
        """检查 Authorization Header"""
        # 如果未配置 token，跳过检查（开发模式）
        if not self._a2a_token:
            return True, ""
        
        auth_header = request.get("headers", {}).get("authorization", "")
        
        if not auth_header:
            return False, "Missing Authorization header"
        
        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False, "Invalid Authorization format. Use: Bearer <token>"
        
        token = parts[1]
        if token != self._a2a_token:
            return False, "Invalid token"
        
        return True, ""

    async def _inject_message(self, content: str, msg_id: str, future: asyncio.Future):
        """通过事件总线注入消息到 AstrBot"""
        try:
            if not self._event_bus:
                future.set_result("事件总线未就绪")
                return
            
            # 构造虚拟事件
            class FakeEvent:
                def __init__(self, text):
                    self.message_str = text
                    self.session_id = f"a2a-{msg_id}"
                    self.user_id = "a2a-gateway"
                    self.group_id = None
                    
                async def plain_result(self, text):
                    future.set_result(text)
                    return [Plain(text=text)]
                
                async def image_result(self, image_url):
                    return []
            
            # 发布到事件总线
            fake_event = FakeEvent(content)
            await self._event_bus.emit("astrbot_message", fake_event)
            
        except Exception as e:
            logger.error(f"[A2A Gateway] 注入消息失败: {e}")
            future.set_result(f"处理失败: {str(e)}")

    def set_response(self, msg_id: str, response: str):
        """设置响应（供外部调用）"""
        future = self._pending_requests.get(str(msg_id))
        if future and not future.done():
            future.set_result(response)

    # ==================== 指令处理 ====================

    @filter.command("a2a")
    async def handle_a2a(self, event: AstrMessageEvent):
        """A2A Gateway 主指令"""
        token_display = self._a2a_token[:8] + "..." if self._a2a_token else "未设置"
        
        yield event.plain_result(
            f"📡 A2A Gateway v1.1.0\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"模式: Client + Server\n"
            f"Token: {token_display}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"/a2a list          - 查看节点列表\n"
            f"/a2a add <name> <url> [token] - 添加节点\n"
            f"/a2a remove <name> - 删除节点\n"
            f"/a2a send <name> <msg> - 发送消息\n"
            f"/a2a status        - 查看系统状态\n"
            f"/a2a tasks         - 查看任务列表\n"
            f"/a2a token         - 查看/重置 Token"
        )

    @filter.command("a2a-list")
    async def cmd_list(self, event: AstrMessageEvent):
        """列出所有已配置的节点"""
        if not self.peers:
            yield event.plain_result("📭 暂无已配置的节点\n使用 /a2a add <名称> <AgentCard URL> 添加")
            return

        lines = ["🌐 A2A 节点列表\n━━━━━━━━━━━━━━━━"]
        for name, peer in self.peers.items():
            status_icon = "🟢" if peer.enabled else "🔴"
            failure_info = f" (失败{peer.failure_count}次)" if peer.failure_count > 0 else ""
            auth_info = f" [{peer.auth_type}]" if peer.auth_type else ""
            lines.append(
                f"{status_icon} {name}{auth_info}\n"
                f"   URL: {peer.base_url}\n"
                f"   Skills: {', '.join(peer.skills) or '未设置'}{failure_info}"
            )
        
        yield event.plain_result("\n".join(lines))

    @filter.command("a2a-add")
    async def cmd_add(self, event: AstrMessageEvent):
        """添加新节点"""
        args = event.message_str.strip().split()
        
        if len(args) < 2:
            yield event.plain_result(
                "❌ 参数不足\n用法: /a2a add <名称> <AgentCard URL> [认证Token]"
            )
            return
        
        name = args[0]
        agent_card_url = args[1]
        token = args[2] if len(args) > 2 else ""
        
        # 处理 base_url：从 AgentCard URL 提取
        base_url = agent_card_url.rstrip("/").replace("/agent.json", "").replace("/.well-known/agent.json", "")
        
        # 尝试获取 Agent Card 获取技能列表
        skills = []
        auth_type = ""
        
        try:
            card = await self.client.get_agent_card(agent_card_url, "bearer" if token else "", token)
            skills = card.get("skills", [])
            if token:
                auth_type = "bearer"
        except Exception as e:
            logger.warning(f"[A2A Gateway] 获取 Agent Card 失败: {e}")
        
        peer = Peer(
            name=name,
            agent_card_url=agent_card_url,
            base_url=base_url,
            auth_type=auth_type,
            token=token,
            skills=[s.get("id", str(s)) if isinstance(s, dict) else str(s) for s in skills],
            enabled=True,
            failure_count=0,
            created_at=datetime.now().isoformat()
        )
        
        self.peers[name] = peer
        self._save_peers()
        
        skill_info = f"\n   发现技能: {', '.join(peer.skills) or '无'}" if skills else ""
        yield event.plain_result(
            f"✅ 节点 [{name}] 添加成功\n"
            f"   URL: {base_url}{skill_info}"
        )

    @filter.command("a2a-remove")
    async def cmd_remove(self, event: AstrMessageEvent):
        """删除节点"""
        args = event.message_str.strip().split()
        
        if len(args) < 1:
            yield event.plain_result("❌ 参数不足\n用法: /a2a remove <名称>")
            return
        
        name = args[0]
        
        if name not in self.peers:
            yield event.plain_result(f"❌ 节点 [{name}] 不存在")
            return
        
        del self.peers[name]
        self._save_peers()
        yield event.plain_result(f"🗑️ 节点 [{name}] 已删除")

    @filter.command("a2a-send")
    async def cmd_send(self, event: AstrMessageEvent):
        """发送消息给指定节点"""
        args = event.message_str.strip().split(maxsplit=1)
        
        if len(args) < 2:
            yield event.plain_result("❌ 参数不足\n用法: /a2a send <节点名> <消息>")
            return
        
        name = args[0]
        message_text = args[1]
        
        if name not in self.peers:
            yield event.plain_result(f"❌ 节点 [{name}] 不存在\n使用 /a2a list 查看已有节点")
            return
        
        peer = self.peers[name]
        
        if not peer.enabled:
            yield event.plain_result(f"⚠️ 节点 [{name}] 已禁用（失败次数过多）")
            return
        
        # 创建任务
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            task_id=task_id,
            peer_name=name,
            status="pending",
            created_at=datetime.now().isoformat()
        )
        self.tasks[task_id] = task
        
        yield event.plain_result(f"📤 正在发送消息到 [{name}]...\nTask ID: {task_id}")
        
        try:
            task.status = "running"
            
            # 构建 A2A 消息格式
            a2a_message = {
                "jsonrpc": "2.0",
                "id": task_id,
                "method": "message",
                "params": {
                    "message": {
                        "role": "user",
                        "content": message_text
                    }
                }
            }
            
            # 发送到远程 Agent
            result = await self.client.send_message(
                peer.base_url,
                a2a_message,
                peer.auth_type,
                peer.token
            )
            
            task.status = "completed"
            task.result = result
            
            # 提取响应内容
            response_text = self._extract_response(result)
            yield event.plain_result(
                f"✅ [{name}] 响应:\n{response_text}"
            )
            
        except httpx.TimeoutException:
            task.status = "failed"
            task.error = "请求超时"
            peer.failure_count += 1
            self._save_peers()
            yield event.plain_result(f"⏱️ [{name}] 请求超时")
            
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            peer.failure_count += 1
            self._save_peers()
            yield event.plain_result(f"❌ [{name}] 请求失败: {e}")

    @filter.command("a2a-status")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看系统状态"""
        total_peers = len(self.peers)
        enabled_peers = sum(1 for p in self.peers.values() if p.enabled)
        disabled_peers = total_peers - enabled_peers
        total_tasks = len(self.tasks)
        completed_tasks = sum(1 for t in self.tasks.values() if t.status == "completed")
        failed_tasks = sum(1 for t in self.tasks.values() if t.status == "failed")
        
        token_status = f"{self._a2a_token[:8]}..." if self._a2a_token else "未设置"
        
        yield event.plain_result(
            f"📊 A2A Gateway 状态\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"版本: v1.1.0 (Client+Server)\n"
            f"Token: {token_status}\n"
            f"\n"
            f"节点: {total_peers} 个\n"
            f"  🟢 启用: {enabled_peers}\n"
            f"  🔴 禁用: {disabled_peers}\n"
            f"\n"
            f"任务: {total_tasks} 个\n"
            f"  ✅ 完成: {completed_tasks}\n"
            f"  ❌ 失败: {failed_tasks}\n"
            f"\n"
            f"存储: {self._storage_path}"
        )

    @filter.command("a2a-tasks")
    async def cmd_tasks(self, event: AstrMessageEvent):
        """查看任务列表"""
        if not self.tasks:
            yield event.plain_result("📭 暂无任务记录")
            return
        
        lines = ["📋 任务列表\n━━━━━━━━━━━━━━━━"]
        # 按时间倒序显示最近10个
        sorted_tasks = sorted(
            self.tasks.values(),
            key=lambda t: t.created_at,
            reverse=True
        )[:10]
        
        for task in sorted_tasks:
            status_icon = {
                "pending": "⏳",
                "running": "🔄",
                "completed": "✅",
                "failed": "❌"
            }.get(task.status, "❓")
            
            created = task.created_at.split("T")[1][:8] if "T" in task.created_at else task.created_at
            error_hint = f" ({task.error[:20]}...)" if task.error and len(task.error) > 20 else (f" ({task.error})" if task.error else "")
            
            lines.append(
                f"{status_icon} [{task.task_id}] → {task.peer_name}\n"
                f"   {created}{error_hint}"
            )
        
        yield event.plain_result("\n".join(lines))

    @filter.command("a2a-token")
    async def cmd_token(self, event: AstrMessageEvent):
        """查看/重置 Token"""
        args = event.message_str.strip().split()
        
        if len(args) > 0 and args[0].lower() == "reset":
            # 重置 Token
            new_token = secrets.token_urlsafe(32)
            self._a2a_token = new_token
            yield event.plain_result(
                f"🔑 Token 已重置!\n\n"
                f"新 Token:\n`{new_token}`\n\n"
                f"⚠️ 请妥善保管此 Token，连接时需要使用。"
            )
        else:
            # 显示当前 Token
            if self._a2a_token:
                yield event.plain_result(
                    f"🔑 当前 A2A Token:\n\n`{self._a2a_token}`\n\n"
                    f"使用 `/a2a token reset` 重置 Token"
                )
            else:
                yield event.plain_result(
                    f"⚠️ 未配置 Token（开发模式）\n\n"
                    f"建议设置 a2a_token 以确保安全。"
                )

    # ==================== 辅助方法 ====================

    def _extract_response(self, result: Dict[str, Any]) -> str:
        """从 A2A 响应中提取文本内容"""
        if not result:
            return "(空响应)"
        
        # 支持多种响应格式
        content = result.get("result", {}).get("content", [])
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                return first.get("text", first.get("type", str(result)))
            return str(first)
        
        # 简化格式
        if "text" in result:
            return result["text"]
        if "message" in result:
            msg = result["message"]
            if isinstance(msg, dict):
                return msg.get("content", str(msg))
            return str(msg)
        
        return str(result)[:500]
