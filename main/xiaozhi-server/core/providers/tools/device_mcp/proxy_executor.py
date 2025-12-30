"""设备端MCP工具代理执行器 - 通过HTTP API代理调用设备端工具"""

import aiohttp
from typing import Dict, Any
from ..base import ToolType, ToolDefinition, ToolExecutor
from plugins_func.register import Action, ActionResponse
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class DeviceMCPProxyExecutor(ToolExecutor):
    """设备端MCP工具代理执行器
    
    通过HTTP API代理调用运行在app.py中的设备端MCP工具，
    用于mcp_tool_server.py独立进程场景。
    """

    def __init__(self, conn, proxy_url: str, auth_token: str = None, internal_api_key: str = None):
        """
        Args:
            conn: 连接处理器（用于获取工具列表）
            proxy_url: 代理API的基础URL，如 http://127.0.0.1:8003
            auth_token: JWT认证token（可选）
            internal_api_key: 内部API密钥（可选，用于Docker环境）
        """
        self.conn = conn
        self.proxy_url = proxy_url.rstrip("/")
        self.auth_token = auth_token
        self.internal_api_key = internal_api_key
        self.logger = logger

    async def execute(
        self, conn, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """通过HTTP API代理执行设备端MCP工具"""
        url = f"{self.proxy_url}/internal/tool/call"
        
        headers = {"Content-Type": "application/json"}
        # 优先使用内部API密钥（Docker环境）
        if self.internal_api_key:
            headers["X-Internal-Key"] = self.internal_api_key
        elif self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        
        # Extract device_id from arguments if provided (optional targeting)
        args = dict(arguments) if arguments else {}
        device_id = args.pop("device_id", None)
        
        payload = {
            "tool_name": tool_name,
            "arguments": args
        }
        
        # Include device_id in payload if specified
        if device_id:
            payload["device_id"] = device_id
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, 
                    json=payload, 
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=35)
                ) as response:
                    result = await response.json()
                    
                    if response.status == 200 and result.get("success"):
                        return ActionResponse(
                            action=Action.REQLLM,
                            result=str(result.get("result", ""))
                        )
                    elif response.status == 503:
                        # 设备未连接
                        return ActionResponse(
                            action=Action.ERROR,
                            response=result.get("error", "设备未连接")
                        )
                    elif response.status == 504:
                        # 超时
                        return ActionResponse(
                            action=Action.ERROR,
                            response="工具调用超时"
                        )
                    elif response.status == 404:
                        return ActionResponse(
                            action=Action.NOTFOUND,
                            response=result.get("error", f"工具 {tool_name} 不存在")
                        )
                    else:
                        return ActionResponse(
                            action=Action.ERROR,
                            response=result.get("error", f"代理调用失败: HTTP {response.status}")
                        )
                        
        except aiohttp.ClientError as e:
            self.logger.bind(tag=TAG).error(f"代理调用网络错误: {e}")
            return ActionResponse(
                action=Action.ERROR,
                response=f"无法连接到主服务器: {str(e)}"
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"代理调用失败: {e}")
            return ActionResponse(
                action=Action.ERROR,
                response=str(e)
            )

    def get_tools(self) -> Dict[str, ToolDefinition]:
        """获取所有设备端MCP工具（从本地缓存的mcp_client获取）"""
        if not hasattr(self.conn, "mcp_client") or not self.conn.mcp_client:
            return {}

        tools = {}
        mcp_tools = self.conn.mcp_client.get_available_tools()

        for tool in mcp_tools:
            func_def = tool.get("function", {})
            tool_name = func_def.get("name", "")

            if tool_name:
                tools[tool_name] = ToolDefinition(
                    name=tool_name, description=tool, tool_type=ToolType.DEVICE_MCP
                )

        return tools

    def has_tool(self, tool_name: str) -> bool:
        """检查是否有指定的设备端MCP工具"""
        if not hasattr(self.conn, "mcp_client") or not self.conn.mcp_client:
            return False

        return self.conn.mcp_client.has_tool(tool_name)
