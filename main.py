import asyncio
import json
import uuid
import httpx
import os
import secrets
import time
import traceback
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from datetime import datetime

from astrbot.api.all import *
from astrbot.api import AstrBotConfig

logger.critical("💥💥💥 [A2A Gateway] v1.3.1 正在載入模塊... 💥💥💥")

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
    status: str
    created_at: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class A2AClient:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def get_agent_card(self, url: str, auth_type: str = "", token: str = "") -> Dict[str, Any]:
        headers = {}
        if auth_type in ("bearer", "apiKey") and token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def send_message(self, base_url: str, message: Dict[str, Any], auth_type: str = "", token: str = "") -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if auth_type in ("bearer", "apiKey") and token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(base_url, json=message, headers=headers)
            resp.raise_for_status()
            return resp.json()


class A2AGatewayPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None, **kwargs):
        super().__init__(context)
        self.context = context
        self.config = config if config else {}

        self.client = A2AClient(timeout=self.config.get("timeout", 30.0))
        self.peers: Dict[str, Peer] = {}
        self.tasks: Dict[str, Task] = {}
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._pending_timestamps: Dict[str, float] = {}

        # ✅ 强制保存状态列表，用于 /a2a_status 回显
        self.registered_routes: List[str] = []

        self._a2a_token: str = self.config.get("a2a_token", "")
        self._agent_name: str = self.config.get("agent_name", "AstrBot-A2A")
        self._agent_desc: str = self.config.get("agent_description", "AstrBot powered A2A Agent")
        self._auto_register: bool = self.config.get("auto_register", True)

        self._storage_path = self._get_storage_path()
        os.makedirs(self._storage_path, exist_ok=True)

        self._load_peers()

        logger.critical(f"🚀 [A2A Gateway] 插件实例化完成 (v1.3.1), Context ID: {id(self.context)}")

    # ─── Token Getter ───────────────────────────────────────────────────────────
    def get_a2a_token(self) -> str:
        """
        防御性 Token 获取，优先级：内存变量 > 配置文件 > admin123 兜底
        """
        token = getattr(self, "_a2a_token", "")
        if not token and self.config:
            token = self.config.get("a2a_token", "")
        return token if token else "admin123"

    def _get_storage_path(self) -> str:
        if self.context and hasattr(self.context, 'get_plugin_data_dir'):
            return self.context.get_plugin_data_dir()
        return "/AstrBot/data/plugins_data/a2a_gateway"

    def _load_peers(self):
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
        peers_file = os.path.join(self._storage_path, "peers.json")
        data = {name: asdict(p) for name, p in self.peers.items()}
        with open(peers_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _cleanup_stale_requests(self, max_age: float = 300.0):
        current_time = time.time()
        stale_ids = [
            msg_id for msg_id, timestamp in self._pending_timestamps.items()
            if current_time - timestamp > max_age
        ]
        for msg_id in stale_ids:
            future = self._pending_requests.pop(msg_id, None)
            if future and not future.done():
                future.set_result("请求超时，已被清理")
            self._pending_timestamps.pop(msg_id, None)
        if stale_ids:
            logger.warning(f"[A2A Gateway] 清理了 {len(stale_ids)} 个超时请求")

    async def init(self, context: Context, config: AstrBotConfig = None, **kwargs):
        logger.critical(f"DEBUG: Entering init, context is {type(self.context)}")
        await super().init(context)
        logger.critical(f"⚡ [A2A Gateway] >>> 开始异步初始化 (init), Context ID: {id(self.context)}")
        self._cleanup_stale_requests()

        await asyncio.sleep(2)

        logger.critical(f"🔑 [A2A Gateway] Token 策略已就位，GETTER: 内存 > 配置 > admin123")

        if self._auto_register:
            logger.critical("🛣️ [A2A Gateway] >>> 启动异步守护士台路由注册任务...")
            asyncio.create_task(self.delay_register())

            loop = asyncio.get_event_loop()
            loop.call_later(15, lambda: asyncio.create_task(self.delay_register()))
            logger.critical("🕐 [A2A Gateway] >>> 已设置 15 秒后备注册任务 (call_later)")
        else:
            logger.critical("⚠️ [A2A Gateway] auto_register 已禁用，跳过 Web 路由注册")

        logger.critical(f"🏁 [A2A Gateway] ✅ 插件初始化完成 (v1.3.1), Context ID: {id(self.context)}")

    async def on_load(self):
        pass

    async def delay_register(self):
        try:
            logger.critical("⏳ [A2A Gateway] 异步守护任务启动，等待 15 秒让系统稳定...")
            await asyncio.sleep(15)
            logger.critical("🛣️ [A2A Gateway] 延迟等待完成，开始执行路由注册...")
            await self._register_web_routes()
        except Exception as e:
            logger.critical(f"❌ [A2A Gateway] delay_register 异常: {e}")
            logger.critical(traceback.format_exc())

    async def _register_web_routes(self):
        try:
            logger.critical("🌐 [A2A Gateway] >>> 开始注册 Web 路由")
            if not self.context:
                logger.warning("[A2A Gateway] context 不可用，跳过 Web 路由注册")
                return

            has_api = hasattr(self.context, 'register_web_api')
            logger.critical(f"🔍 [A2A Gateway] context.register_web_api 是否存在: {has_api}")
            
            ctx_attrs = [attr for attr in dir(self.context) if not attr.startswith('_')]
            logger.critical(f"📋 [A2A Gateway] context 属性列表: {ctx_attrs}")
            
            if not has_api:
                logger.critical("❌ [A2A Gateway] context.register_web_api 不存在，路由注册失败")
                return

            registered_count = 0
            prefix = "/astrbot_plugin_a2a_gateway"

            logger.critical(f"📡 [A2A Gateway] >>> 尝试注册 {prefix}/test 路由")
            try:
                async def test_handler(*args, **kwargs):
                    return {"status": "ok", "message": "A2A Gateway Test Route v1.3.1"}

                self.context.register_web_api(
                    route=f"{prefix}/test",
                    view_handler=test_handler,
                    methods=["GET"],
                    desc="Test Route"
                )
                self.registered_routes.append(f"/api/plug{prefix}/test")
                logger.critical(f"✅ [A2A Gateway] {prefix}/test 路由注册成功 → /api/plug{prefix}/test")
                registered_count += 1
            except Exception as e:
                logger.critical(f"❌ [A2A Gateway] {prefix}/test 路由注册失败: {e}")
                logger.critical(traceback.format_exc())

            logger.critical(f"🆔 [A2A Gateway] >>> 尝试注册 {prefix}/agent.json 路由")
            try:
                self.context.register_web_api(
                    route=f"{prefix}/agent.json",
                    view_handler=self._handle_agent_card,
                    methods=["GET"],
                    desc="A2A Agent Card"
                )
                self.registered_routes.append(f"/api/plug{prefix}/agent.json")
                logger.critical(f"✅ [A2A Gateway] {prefix}/agent.json 路由注册成功 → /api/plug{prefix}/agent.json")
                registered_count += 1
            except Exception as e:
                logger.critical(f"❌ [A2A Gateway] {prefix}/agent.json 路由注册失败: {e}")
                logger.critical(traceback.format_exc())

            logger.critical(f"🚪 [A2A Gateway] >>> 尝试注册 {prefix}/api/a2a/proxy 路由")
            try:
                self.context.register_web_api(
                    route=f"{prefix}/api/a2a/proxy",
                    view_handler=self._handle_a2a_message,
                    methods=["POST"],
                    desc="A2A JSON-RPC Proxy"
                )
                self.registered_routes.append(f"/api/plug{prefix}/api/a2a/proxy")
                logger.critical(f"✅ [A2A Gateway] {prefix}/api/a2a/proxy 路由注册成功 → /api/plug{prefix}/api/a2a/proxy")
                registered_count += 1
            except Exception as e:
                logger.critical(f"❌ [A2A Gateway] {prefix}/api/a2a/proxy 路由注册失败: {e}")
                logger.critical(traceback.format_exc())

            logger.critical(f"🏁 [A2A Gateway] 路由注册完成，共注册 {registered_count} 个路由")
            logger.critical(f"📋 [A2A Gateway] 当前 registered_routes: {self.registered_routes}")
        except Exception as e:
            logger.critical(f"❌ [A2A Gateway] _register_web_routes 顶层异常: {e}")
            logger.critical(traceback.format_exc())

    async def _handle_agent_card(self, *args, **kwargs) -> Dict[str, Any]:
        logger.info("[A2A Gateway] >>> 收到 /agent.json 请求")
        if self.get_a2a_token():
            try:
                from quart import request
                auth_header = request.headers.get("Authorization", "")
                if not self._verify_token(auth_header):
                    return {"error": "Unauthorized", "code": 401}
            except ImportError:
                pass

        return {
            "name": self._agent_name,
            "description": self._agent_desc,
            "version": "1.3.1",
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "stateTransitions": False
            },
            "skills": [
                {"id": "general-chat", "name": "General Chat", "description": "通用对话能力"}
            ],
            "url": f"/api/plug/astrbot_plugin_a2a_gateway/api/a2a/proxy"
        }

    async def _handle_a2a_message(self, *args, **kwargs) -> Dict[str, Any]:
        logger.info("[A2A Gateway] >>> 收到 /api/a2a/proxy 请求")
        self._cleanup_stale_requests(max_age=60.0)

        if self.get_a2a_token():
            try:
                from quart import request
                auth_header = request.headers.get("Authorization", "")
                if not self._verify_token(auth_header):
                    return {
                        "jsonrpc": "2.0",
                        "error": {"code": -32600, "message": "Unauthorized"}
                    }
            except ImportError:
                pass

        try:
            try:
                from quart import request
                body = await request.get_json(force=True)
            except Exception:
                body = {}

            if not body:
                return {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}

            jsonrpc = body.get("jsonrpc")
            method = body.get("method")
            msg_id = body.get("id")
            params = body.get("params", {})

            if jsonrpc != "2.0":
                return {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}}

            if method == "message":
                message_data = params.get("message", {})
                content = message_data.get("content", "")

                future: asyncio.Future = asyncio.Future()
                self._pending_requests[str(msg_id)] = future
                self._pending_timestamps[str(msg_id)] = time.time()

                try:
                    await self._inject_message(content, msg_id)
                    try:
                        response_text = await asyncio.wait_for(
                            future,
                            timeout=self.config.get("timeout", 30.0)
                        )
                    except asyncio.TimeoutError:
                        response_text = "处理超时，请重试"

                    return {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"content": [{"type": "text", "text": response_text}]}
                    }
                finally:
                    self._pending_requests.pop(str(msg_id), None)
                    self._pending_timestamps.pop(str(msg_id), None)

            elif method == "tasks/cancel":
                return {"jsonrpc": "2.0", "id": msg_id, "result": {"ok": True}}
            else:
                return {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Method not found: {method}"}}

        except Exception as e:
            logger.error(f"[A2A Gateway] 处理请求失败: {e}")
            return {"jsonrpc": "2.0", "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}

    def _verify_token(self, auth_header: str) -> bool:
        if not auth_header:
            return False
        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False
        return parts[1] == self.get_a2a_token()

    async def _inject_message(self, content: str, msg_id: str):
        try:
            pending = self._pending_requests

            class FakeEvent:
                def __init__(self, text, msg_id, pending_dict):
                    self.message_str = text
                    self.session_id = f"a2a-{msg_id}"
                    self.user_id = "a2a-gateway"
                    self.group_id = None
                    self.platform = "a2a"
                    self.self_id = "a2a-gateway"
                    self.message_id = f"a2a-msg-{msg_id}"
                    self._pending = pending_dict
                    self._source = "a2a-gateway"
                    self.message = [Plain(text=text)]
                    self.type = "a2a_message"
                    self.raw_content = text
                    self.msg_id = msg_id

                @property
                def plain_text(self) -> str:
                    return self.raw_content

                async def plain_result(self, text: str):
                    return await self._pending_result(text)

                async def result(self, message_chain: list):
                    if message_chain and len(message_chain) > 0:
                        first = message_chain[0]
                        text = first.text if hasattr(first, 'text') else str(first)
                    else:
                        text = "(空响应)"
                    return await self._pending_result(text)

                async def _pending_result(self, text: str):
                    future = self._pending.get(str(self.msg_id))
                    if future and not future.done():
                        future.set_result(text)
                    to_send = text if isinstance(text, list) else Plain(text=text)
                    return to_send if isinstance(to_send, list) else [to_send]

            fake_event = FakeEvent(content, msg_id, pending)
            await self.context.post_event(fake_event)
        except Exception as e:
            logger.error(f"[A2A Gateway] 注入消息失败: {e}")
            future = self._pending_requests.get(str(msg_id))
            if future and not future.done():
                future.set_result(f"处理失败: {str(e)}")

    @command("a2a")
    async def handle_a2a(self, event: AstrMessageEvent):
        token = self.get_a2a_token()
        token_display = token[:8] + "..." if token else "未设置"
        routes_info = "\n   ".join(self.registered_routes) if self.registered_routes else "(等待注册)"
        yield event.plain_result(
            f"📡 A2A Gateway v1.3.1\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Token: {token_display}\n"
            f"已注册路由:\n   {routes_info}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"/a2a_list      - 查看节点列表\n"
            f"/a2a_add       - 添加节点\n"
            f"/a2a_remove    - 删除节点\n"
            f"/a2a_send      - 发送消息\n"
            f"/a2a_status    - 查看系统状态\n"
            f"/a2a_tasks     - 查看任务列表\n"
            f"/a2a_token     - 查看/重置 Token\n"
            f"/a2a_force_reg - 强制重新注册路由\n"
            f"/a2a_debug_ctx - 打印 context 属性"
        )

    @command("a2a_list")
    async def cmd_list(self, event: AstrMessageEvent):
        if not self.peers:
            yield event.plain_result("📭 暂无节点\n使用 `/a2a_add <名称> <URL>` 添加")
            return
        lines = ["🌐 A2A 节点列表\n━━━━━━━━━━━━━━━━"]
        for name, peer in self.peers.items():
            status_icon = "🟢" if peer.enabled else "🔴"
            lines.append(f"{status_icon} {name}\n   URL: {peer.base_url}")
        yield event.plain_result("\n".join(lines))

    # ─── 参数解析通用函数 ──────────────────────────────────────────────────────
    def _strip_command_prefix(self, raw_text: str, cmd_name: str) -> str:
        """去掉指令前缀，确保 args[0] 是参数而不是命令名"""
        for prefix in [f"/{cmd_name}", f"{cmd_name}"]:
            if raw_text.startswith(prefix):
                return raw_text[len(prefix):].strip()
        return raw_text.strip()

    @command("a2a_add")
    async def cmd_add(self, event: AstrMessageEvent):
        raw_text = self._strip_command_prefix(event.message_str.strip(), "a2a_add")
        args = raw_text.split()

        if len(args) < 2:
            yield event.plain_result("❌ 用法: `/a2a_add <名称> <AgentCard URL> [token]`")
            return

        name = args[0]
        agent_card_url = args[1]
        token = args[2] if len(args) > 2 else ""

        # ✅ 解析日志，打印防止低级错误
        logger.info(f"[A2A Gateway] 解析添加参数: name={name}, url={agent_card_url}, token={'***' if token else '无'}")

        base_url = agent_card_url.rstrip("/")
        for suffix in ["/agent.json", "/.well-known/agent.json"]:
            if base_url.endswith(suffix):
                base_url = base_url[:-len(suffix)]
                break

        skills = []
        auth_type = ""

        try:
            card = await self.client.get_agent_card(agent_card_url, "bearer" if token else "", token)
            skills = card.get("skills", [])
            if token:
                auth_type = "bearer"
            logger.info(f"[A2A Gateway] 获取 Agent Card 成功: {card.get('name', 'unknown')}")
        except Exception as e:
            logger.warning(f"[A2A Gateway] 获取 Agent Card 失败: {e}")
            yield event.plain_result(f"⚠️ 获取 Agent Card 失败，节点可能无法通信: {e}")

        peer = Peer(
            name=name, agent_card_url=agent_card_url, base_url=base_url,
            auth_type=auth_type, token=token,
            skills=[s.get("id", str(s)) if isinstance(s, dict) else str(s) for s in skills],
            enabled=True, failure_count=0, created_at=datetime.now().isoformat()
        )

        self.peers[name] = peer
        self._save_peers()
        yield event.plain_result(f"✅ 节点 [{name}] 添加成功\n   URL: {base_url}")

    @command("a2a_remove")
    async def cmd_remove(self, event: AstrMessageEvent):
        raw_text = self._strip_command_prefix(event.message_str.strip(), "a2a_remove")
        args = raw_text.split()

        if len(args) < 1:
            yield event.plain_result("❌ 用法: `/a2a_remove <名称>`")
            return
        name = args[0]

        logger.info(f"[A2A Gateway] 解析删除参数: name={name}")

        if name not in self.peers:
            yield event.plain_result(f"❌ 节点 [{name}] 不存在")
            return
        del self.peers[name]
        self._save_peers()
        yield event.plain_result(f"🗑️ 节点 [{name}] 已删除")

    @command("a2a_send")
    async def cmd_send(self, event: AstrMessageEvent):
        raw_text = self._strip_command_prefix(event.message_str.strip(), "a2a_send")
        args = raw_text.split(maxsplit=1)

        if len(args) < 2:
            yield event.plain_result("❌ 用法: `/a2a_send <节点名> <消息>`")
            return

        name = args[0]
        message_text = args[1]

        logger.info(f"[A2A Gateway] 解析发送参数: name={name}, msg_len={len(message_text)}")

        if name not in self.peers:
            yield event.plain_result(f"❌ 节点 [{name}] 不存在")
            return

        peer = self.peers[name]
        if not peer.enabled:
            yield event.plain_result(f"⚠️ 节点 [{name}] 已禁用")
            return

        task_id = str(uuid.uuid4())[:8]
        task = Task(task_id=task_id, peer_name=name, status="pending", created_at=datetime.now().isoformat())
        self.tasks[task_id] = task

        yield event.plain_result(f"📤 正在发送消息到 [{name}]...\nTask ID: {task_id}")

        try:
            task.status = "running"
            a2a_message = {
                "jsonrpc": "2.0", "id": task_id, "method": "message",
                "params": {"message": {"role": "user", "content": message_text}}
            }
            result = await self.client.send_message(peer.base_url, a2a_message, peer.auth_type, peer.token)
            task.status = "completed"
            task.result = result
            response_text = self._extract_response(result)
            yield event.plain_result(f"✅ [{name}] 响应:\n\n{response_text}")
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

    @command("a2a_status")
    async def cmd_status(self, event: AstrMessageEvent):
        total_peers = len(self.peers)
        enabled_peers = sum(1 for p in self.peers.values() if p.enabled)
        total_tasks = len(self.tasks)
        completed_tasks = sum(1 for t in self.tasks.values() if t.status == "completed")

        registered = list(self.registered_routes)
        if self.context and hasattr(self.context, 'registered_web_apis'):
            core_registered = [r[0] for r in self.context.registered_web_apis]
            if core_registered and not registered:
                registered = [f"/api/plug/{r}" for r in core_registered]

        routes_display = "\n   ".join(registered) if registered else "(延迟注册中，15秒后刷新)"
        yield event.plain_result(
            f"📊 A2A Gateway 状态\n━━━━━━━━━━━━━━━━━━━━\n"
            f"版本: v1.3.1\n"
            f"节点: {total_peers} 个 (🟢 {enabled_peers})\n"
            f"任务: {total_tasks} 个 (✅ {completed_tasks})\n"
            f"存储: {self._storage_path}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"已注册路由:\n   {routes_display}"
        )

    @command("a2a_tasks")
    async def cmd_tasks(self, event: AstrMessageEvent):
        if not self.tasks:
            yield event.plain_result("📭 暂无任务记录")
            return
        lines = ["📋 任务列表\n━━━━━━━━━━━━━━━━"]
        for task in sorted(self.tasks.values(), key=lambda t: t.created_at, reverse=True)[:10]:
            icon = {"pending": "⏳", "running": "🔄", "completed": "✅", "failed": "❌"}.get(task.status, "❓")
            lines.append(f"{icon} [{task.task_id}] → {task.peer_name}")
        yield event.plain_result("\n".join(lines))

    @command("a2a_token")
    async def cmd_token(self, event: AstrMessageEvent):
        raw_text = self._strip_command_prefix(event.message_str.strip(), "a2a_token")
        args = raw_text.split()

        logger.info(f"[A2A Gateway] Token 指令参数: {args}")

        if len(args) > 0 and args[0].lower() == "reset":
            new_token = secrets.token_urlsafe(32)
            self._a2a_token = new_token
            yield event.plain_result(f"🔑 Token 已重置!\n\n`{new_token}`")
        else:
            current_token = self.get_a2a_token()
            yield event.plain_result(f"🔑 当前 Token:\n\n`{current_token}`")

    @command("a2a_force_reg")
    async def cmd_force_reg(self, event: AstrMessageEvent):
        yield event.plain_result("🔧 正在强制注册 Web 路由，请查看日志...")
        try:
            await self._register_web_routes()
            yield event.plain_result("✅ 路由注册尝试完成，请发送 /a2a_status 查看结果")
        except Exception as e:
            yield event.plain_result(f"❌ 路由注册失败: {e}\n\n{traceback.format_exc()}")

    @command("a2a_debug_ctx")
    async def cmd_debug_ctx(self, event: AstrMessageEvent):
        ctx_attrs = [attr for attr in dir(self.context) if not attr.startswith('_')]
        yield event.plain_result(
            f"📋 Context 属性列表 (共 {len(ctx_attrs)} 个):\n" + 
            "\n".join(f"  • {attr}" for attr in ctx_attrs)
        )

    def _extract_response(self, result: Dict[str, Any]) -> str:
        if not result:
            return "(空响应)"
        content = result.get("result", {}).get("content", [])
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                return first.get("text", str(first))
            return str(first)
        return str(result)[:500]
