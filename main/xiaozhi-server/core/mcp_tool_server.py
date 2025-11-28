"""
Expose Xiaozhi's UnifiedToolHandler through an MCP SSE server so external
clients (e.g. LangChain) can discover and invoke local tools via HTTP.
"""
from __future__ import annotations

import os.path as osp
import sys
sys.path.append(osp.abspath(osp.dirname(osp.dirname(__file__))))

import argparse
import asyncio
import json
import signal
import threading
from typing import Any, Dict, List, Optional

from config.logger import setup_logging
from config.settings import load_config
from core.connection import ConnectionHandler
from core.providers.tools.unified_tool_handler import UnifiedToolHandler
from core.utils.modules_initialize import initialize_modules
from core.providers.tools.device_mcp.mcp_storage import load_device_tools
from core.providers.tools.device_mcp.proxy_executor import DeviceMCPProxyExecutor
from core.providers.tools.base import ToolType
from mcp.server.fastmcp import FastMCP
from mcp.types import Content, TextContent, Tool as MCPTool
from plugins_func.register import ActionResponse

logger = setup_logging()


def _json_dumps(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return str(data)


def _format_action_response(response: ActionResponse) -> str:
    parts: List[str] = []
    if response.response:
        parts.append(str(response.response))
    if response.result and response.result != response.response:
        parts.append(
            response.result
            if isinstance(response.result, str)
            else _json_dumps(response.result)
        )
    if not parts:
        parts.append(getattr(response.action, "message", response.action.name))
    return "\n".join(part for part in parts if part)


class XiaozhiMCPServer(FastMCP):
    """FastMCP server that proxies Xiaozhi ToolManager calls."""

    def __init__(
        self,
        tool_handler: UnifiedToolHandler,
        *,
        name: str,
        instructions: str,
        host: str,
        port: int,
        mount_path: str,
        sse_path: str,
        message_path: str,
        log_level: str,
    ) -> None:
        super().__init__(
            name=name,
            instructions=instructions,
            host=host,
            port=port,
            mount_path=mount_path,
            sse_path=sse_path,
            message_path=message_path,
            log_level=log_level.upper(),
        )
        self.tool_handler = tool_handler

    async def list_tools(self) -> List[MCPTool]:
        # Refresh cached tool metadata to ensure new registrations are visible.
        self.tool_handler.upload_functions_desc()
        tools: List[MCPTool] = []
        for description in self.tool_handler.get_functions():
            func_def = None
            if isinstance(description, dict):
                if description.get("type") == "function":
                    func_def = description.get("function")
                else:
                    func_def = description
            if not isinstance(func_def, dict):
                continue

            name = func_def.get("name")
            if not name:
                continue

            parameters = func_def.get("parameters") or {
                "type": "object",
                "properties": {},
            }
            tools.append(
                MCPTool(
                    name=name,
                    description=func_def.get("description", ""),
                    inputSchema=parameters,
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> List[Content]:
        response = await self.tool_handler.tool_manager.execute_tool(
            name, arguments or {}
        )
        text = _format_action_response(response)
        return [TextContent(type="text", text=text)]


def _start_background_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()

    def _runner() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_runner, name="xiaozhi-tool-loop", daemon=True)
    thread.start()
    return loop


async def _build_connection(
    config: Dict[str, Any],
    modules: Dict[str, Any],
) -> ConnectionHandler:
    conn = ConnectionHandler(
        config,
        modules.get("vad"),
        modules.get("asr"),
        modules.get("llm"),
        modules.get("memory"),
        modules.get("intent"),
    )
    # Provide basic metadata expected by some plugins.
    conn.client_ip = "127.0.0.1"
    conn.conn_from_mqtt_gateway = False

    conn.func_handler = UnifiedToolHandler(conn)
    await conn.func_handler._initialize()
    conn.func_handler.tool_manager.refresh_tools()

    # 如果之前有设备通过 MCP 客户端上报过 self_* 工具，
    # 则在 MCP 工具服务器中恢复这些设备端 MCP 工具。
    device_tools = load_device_tools()
    if device_tools:
        try:
            # 将保存的工具直接注入到 device_mcp 执行器使用的 mcp_client 结构中
            # 注意这里不需要真正的 websocket，只是为了让 ToolManager 能够看到这些工具。
            from core.providers.tools.device_mcp.mcp_client import MCPClient

            mcp_client = MCPClient()
            for tool in device_tools:
                # 逐个恢复工具
                fut = asyncio.ensure_future(mcp_client.add_tool(tool))
                await fut

            conn.mcp_client = mcp_client
            await mcp_client.set_ready(True)

            # 构建代理URL - 使用主服务器的HTTP端口
            server_config = config.get("server", {})
            proxy_host = server_config.get("ip", "127.0.0.1")
            # 如果服务器绑定到0.0.0.0，使用127.0.0.1进行本地连接
            if proxy_host == "0.0.0.0":
                proxy_host = "127.0.0.1"
            # 支持通过环境变量或配置覆盖代理主机（用于Docker环境）
            import os
            proxy_host = os.environ.get("TOOL_PROXY_HOST", server_config.get("tool_proxy_host", proxy_host))
            proxy_port = int(server_config.get("http_port", 8003))
            proxy_url = f"http://{proxy_host}:{proxy_port}"
            
            # 获取内部API密钥（优先用于Docker环境）
            internal_api_key = os.environ.get(
                "INTERNAL_API_KEY", 
                server_config.get("internal_api_key", "")
            )
            
            # 获取认证token（如果配置了auth_key且没有内部API密钥）
            auth_token = None
            if not internal_api_key:
                auth_key = server_config.get("auth_key", "")
                if auth_key:
                    from core.utils.auth import AuthToken
                    auth = AuthToken(auth_key)
                    auth_token = auth.generate_token("mcp_tool_server")

            # 创建代理执行器替换原有的设备MCP执行器
            proxy_executor = DeviceMCPProxyExecutor(
                conn, proxy_url, auth_token, internal_api_key
            )
            
            # 替换ToolManager中的DEVICE_MCP执行器为代理执行器
            conn.func_handler.tool_manager.register_executor(
                ToolType.DEVICE_MCP, proxy_executor
            )

            # 让 ToolManager 重新发现这些设备端 MCP 工具
            conn.func_handler.tool_manager.refresh_tools()
            logger.info(
                "[MCP-TOOLS-RESTORE] 已从本地恢复设备端 MCP 工具 %d 个，将通过 %s 代理调用",
                len(device_tools),
                proxy_url,
            )
            # 重新输出当前支持的函数列表（包含恢复的设备端工具）
            conn.func_handler.current_support_functions()
        except Exception as exc:
            logger.error(f"[MCP-TOOLS-RESTORE] 恢复设备端 MCP 工具失败: {exc}")

    return conn


def _init_connection(
    loop: asyncio.AbstractEventLoop,
    config: Dict[str, Any],
) -> ConnectionHandler:
    init_llm = "LLM" in config.get("selected_module", {})
    init_memory = "Memory" in config.get("selected_module", {})
    init_intent = "Intent" in config.get("selected_module", {})

    modules = initialize_modules(
        logger,
        config,
        init_vad=False,
        init_asr=False,
        init_llm=init_llm,
        init_tts=False,
        init_memory=init_memory,
        init_intent=init_intent,
    )

    future = asyncio.run_coroutine_threadsafe(
        _build_connection(config, modules),
        loop,
    )
    return future.result()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Expose Xiaozhi tools over MCP (SSE transport)."
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host interface for the MCP server (overrides config).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for the MCP server (overrides config).",
    )
    parser.add_argument(
        "--mount-path",
        default=None,
        help="Mount path for the MCP server (overrides config).",
    )
    parser.add_argument(
        "--sse-path",
        default=None,
        help="SSE subscription path (defaults to /sse).",
    )
    parser.add_argument(
        "--message-path",
        default=None,
        help="HTTP message path (defaults to /messages/).",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Visible MCP server name.",
    )
    parser.add_argument(
        "--instructions",
        default=None,
        help="Optional instructions string shown to clients.",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override FastMCP log level.",
    )
    return parser.parse_args()


def _merge_server_settings(
    config: Dict[str, Any],
    args: argparse.Namespace,
) -> Dict[str, Any]:
    defaults = {
        "host": "127.0.0.1",
        "port": 8805,
        "mount_path": "/",
        "sse_path": "/sse",
        "message_path": "/messages/",
        "name": "xiaozhi-tools",
        "instructions": "Unified Xiaozhi tools exposed over MCP.",
        "log_level": "INFO",
    }

    cfg_section: Dict[str, Any] = config.get("mcp_tool_server", {})
    merged = {**defaults, **cfg_section}

    override_map = {
        "host": args.host,
        "port": args.port,
        "mount_path": args.mount_path,
        "sse_path": args.sse_path,
        "message_path": args.message_path,
        "name": args.name,
        "instructions": args.instructions,
        "log_level": args.log_level,
    }

    for key, value in override_map.items():
        if value is not None:
            merged[key] = value

    if merged["mount_path"] not in ("/", ""):
        logger.warning(
            "FastMCP 当前 SSE 实现不支持自定义 mount_path，已强制改为根路径 '/'."
        )
        merged["mount_path"] = "/"
    return merged


def _shutdown_connection(loop: asyncio.AbstractEventLoop, conn: ConnectionHandler):
    async def _cleanup():
        if conn.func_handler:
            await conn.func_handler.cleanup()

    future = asyncio.run_coroutine_threadsafe(_cleanup(), loop)
    try:
        future.result(timeout=20)
    except Exception as exc:  # pragma: no cover - best effort cleanup
        logger.error(f"Failed to cleanup tool handler: {exc}")
    loop.call_soon_threadsafe(loop.stop)


def main() -> None:
    args = _parse_args()
    config = load_config()
    settings = _merge_server_settings(config, args)

    loop = _start_background_loop()
    conn = _init_connection(loop, config)
    tool_handler = conn.func_handler

    server = XiaozhiMCPServer(
        tool_handler=tool_handler,
        name=settings["name"],
        instructions=settings["instructions"],
        host=settings["host"],
        port=int(settings["port"]),
        mount_path=settings["mount_path"],
        sse_path=settings["sse_path"],
        message_path=settings["message_path"],
        log_level=settings["log_level"],
    )

    logger.info(
        "Xiaozhi MCP tool server listening at http://{}:{}{} (SSE: {}, messages: {})",
        settings["host"],
        settings["port"],
        settings["mount_path"],
        settings["sse_path"],
        settings["message_path"],
    )

    def _handle_signal(signum: int, frame: Optional[Any]) -> None:  # pragma: no cover
        logger.info("Received signal %s, shutting down MCP tool server", signum)
        raise KeyboardInterrupt()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_signal)

    try:
        server.run(transport="sse", mount_path=settings["mount_path"])
    finally:
        _shutdown_connection(loop, conn)


if __name__ == "__main__":
    # NOTE: to enable external run as:
    # python core/mcp_tool_server.py --host 0.0.0.0 --port 8805
    main()

