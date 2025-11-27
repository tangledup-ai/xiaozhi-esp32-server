"""内部工具代理处理器 - 用于MCP工具服务器代理调用设备端工具"""

import json
from aiohttp import web
from config.logger import setup_logging
from core.utils.auth import AuthToken
from .base_handler import BaseHandler

TAG = __name__


class ToolProxyHandler(BaseHandler):
    """处理来自MCP工具服务器的工具调用代理请求"""

    def __init__(self, config: dict, ws_server=None):
        super().__init__(config)
        self.ws_server = ws_server

    def set_ws_server(self, ws_server):
        """设置WebSocket服务器引用"""
        self.ws_server = ws_server

    async def handle_options(self, request: web.Request) -> web.Response:
        """处理OPTIONS预检请求"""
        response = web.Response(status=200)
        self._add_cors_headers(response)
        return response

    async def handle_post(self, request: web.Request) -> web.Response:
        """处理工具调用代理请求
        
        请求体格式:
        {
            "tool_name": "self_get_device_status",
            "arguments": {},
            "device_id": "optional_device_id"  # 可选，指定目标设备
        }
        
        响应格式:
        {
            "success": true/false,
            "result": "工具执行结果",
            "error": "错误信息（如果失败）"
        }
        """
        try:
            # 验证请求（内部接口允许本地/可信网络访问）
            auth_header = request.headers.get("Authorization", "")
            is_local = self._is_local_request(request)
            if not is_local and not self._verify_auth(request, auth_header):
                response = web.json_response(
                    {"success": False, "error": "认证失败"},
                    status=401
                )
                self._add_cors_headers(response)
                return response

            # 解析请求体
            try:
                body = await request.json()
            except json.JSONDecodeError:
                response = web.json_response(
                    {"success": False, "error": "无效的JSON请求体"},
                    status=400
                )
                self._add_cors_headers(response)
                return response

            tool_name = body.get("tool_name")
            arguments = body.get("arguments", {})
            target_device_id = body.get("device_id")

            if not tool_name:
                response = web.json_response(
                    {"success": False, "error": "缺少tool_name参数"},
                    status=400
                )
                self._add_cors_headers(response)
                return response

            # 查找有效的设备连接
            conn = self._find_device_connection(target_device_id)
            if not conn:
                response = web.json_response(
                    {"success": False, "error": "没有可用的设备连接"},
                    status=503
                )
                self._add_cors_headers(response)
                return response

            # 检查设备是否支持该工具
            if not hasattr(conn, "mcp_client") or not conn.mcp_client:
                response = web.json_response(
                    {"success": False, "error": "设备未初始化MCP客户端"},
                    status=503
                )
                self._add_cors_headers(response)
                return response

            if not await conn.mcp_client.is_ready():
                response = web.json_response(
                    {"success": False, "error": "设备MCP客户端未就绪"},
                    status=503
                )
                self._add_cors_headers(response)
                return response

            if not conn.mcp_client.has_tool(tool_name):
                response = web.json_response(
                    {"success": False, "error": f"设备不支持工具: {tool_name}"},
                    status=404
                )
                self._add_cors_headers(response)
                return response

            # 执行工具调用
            from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool

            try:
                args_str = json.dumps(arguments) if arguments else "{}"
                result = await call_mcp_tool(conn, conn.mcp_client, tool_name, args_str)
                
                response = web.json_response({
                    "success": True,
                    "result": result
                })
                self._add_cors_headers(response)
                return response

            except TimeoutError:
                response = web.json_response(
                    {"success": False, "error": "工具调用超时"},
                    status=504
                )
                self._add_cors_headers(response)
                return response
            except ValueError as e:
                response = web.json_response(
                    {"success": False, "error": str(e)},
                    status=400
                )
                self._add_cors_headers(response)
                return response
            except Exception as e:
                self.logger.bind(tag=TAG).error(f"工具调用失败: {e}")
                response = web.json_response(
                    {"success": False, "error": f"工具调用失败: {str(e)}"},
                    status=500
                )
                self._add_cors_headers(response)
                return response

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"处理工具代理请求失败: {e}")
            response = web.json_response(
                {"success": False, "error": f"服务器内部错误: {str(e)}"},
                status=500
            )
            self._add_cors_headers(response)
            return response

    def _is_local_request(self, request: web.Request) -> bool:
        """检查请求是否来自本地或可信网络"""
        peername = request.transport.get_extra_info("peername")
        if peername:
            client_ip = peername[0]
            # 允许本地回环地址
            if client_ip in ("127.0.0.1", "::1", "localhost"):
                return True
            # 允许Docker默认网络 (172.17.x.x, 172.18.x.x, etc.)
            if client_ip.startswith("172.") or client_ip.startswith("10."):
                return True
            # 检查配置的可信IP列表
            trusted_ips = self.config.get("server", {}).get("trusted_proxy_ips", [])
            if client_ip in trusted_ips:
                return True
        return False

    def _verify_auth(self, request: web.Request, auth_header: str) -> bool:
        """验证请求认证
        
        支持两种认证方式:
        1. X-Internal-Key header: 简单的内部API密钥（用于服务间通信）
        2. Bearer token: JWT token认证
        """
        # 检查内部API密钥
        internal_key = request.headers.get("X-Internal-Key", "")
        configured_internal_key = self.config.get("server", {}).get("internal_api_key", "")
        if configured_internal_key and internal_key == configured_internal_key:
            return True
        
        # 检查auth_key配置
        auth_key = self.config.get("server", {}).get("auth_key", "")
        
        if not auth_key:
            # 如果没有配置auth_key，允许所有请求（开发模式）
            return True
        
        if not auth_header.startswith("Bearer "):
            return False
        
        token = auth_header[7:]  # 去掉 "Bearer " 前缀
        
        try:
            auth = AuthToken(auth_key)
            # 验证token，返回 (is_valid, device_id)
            is_valid, _ = auth.verify_token(token)
            return is_valid
        except Exception:
            return False

    def _find_device_connection(self, target_device_id: str = None):
        """查找有效的设备连接
        
        Args:
            target_device_id: 目标设备ID，如果为None则返回任意有效连接
            
        Returns:
            ConnectionHandler或None
        """
        if not self.ws_server:
            self.logger.bind(tag=TAG).warning("WebSocket服务器未设置")
            return None

        for conn in self.ws_server.active_connections:
            # 检查连接是否有效
            if not hasattr(conn, "mcp_client") or not conn.mcp_client:
                continue
            
            # 如果指定了目标设备ID，检查是否匹配
            if target_device_id:
                conn_device_id = getattr(conn, "device_id", None)
                if not conn_device_id:
                    # 尝试从headers获取
                    if hasattr(conn, "headers"):
                        conn_device_id = conn.headers.get("device-id")
                
                if conn_device_id != target_device_id:
                    continue
            
            return conn
        
        return None

    async def handle_list_devices(self, request: web.Request) -> web.Response:
        """列出所有已连接的设备"""
        try:
            # 验证请求（内部接口允许本地/可信网络访问）
            auth_header = request.headers.get("Authorization", "")
            is_local = self._is_local_request(request)
            if not is_local and not self._verify_auth(request, auth_header):
                response = web.json_response(
                    {"success": False, "error": "认证失败"},
                    status=401
                )
                self._add_cors_headers(response)
                return response

            devices = []
            if self.ws_server:
                for conn in self.ws_server.active_connections:
                    device_info = {
                        "device_id": None,
                        "has_mcp": False,
                        "mcp_ready": False,
                        "tools": []
                    }
                    
                    # 获取设备ID
                    if hasattr(conn, "headers"):
                        device_info["device_id"] = conn.headers.get("device-id")
                    
                    # 检查MCP状态
                    if hasattr(conn, "mcp_client") and conn.mcp_client:
                        device_info["has_mcp"] = True
                        # 同步检查ready状态（简化处理）
                        device_info["mcp_ready"] = conn.mcp_client.ready
                        if device_info["mcp_ready"]:
                            device_info["tools"] = list(conn.mcp_client.tools.keys())
                    
                    devices.append(device_info)

            response = web.json_response({
                "success": True,
                "devices": devices
            })
            self._add_cors_headers(response)
            return response

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"列出设备失败: {e}")
            response = web.json_response(
                {"success": False, "error": str(e)},
                status=500
            )
            self._add_cors_headers(response)
            return response
