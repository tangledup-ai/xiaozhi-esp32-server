import asyncio
from aiohttp import web
from config.logger import setup_logging
from core.api.ota_handler import OTAHandler
from core.api.vision_handler import VisionHandler
from core.api.tool_proxy_handler import ToolProxyHandler

TAG = __name__


class SimpleHttpServer:
    def __init__(self, config: dict, ws_server=None):
        self.config = config
        self.logger = setup_logging()
        self.ota_handler = OTAHandler(config)
        self.vision_handler = VisionHandler(config)
        self.tool_proxy_handler = ToolProxyHandler(config, ws_server)
        self.ws_server = ws_server

    def set_ws_server(self, ws_server):
        """设置WebSocket服务器引用"""
        self.ws_server = ws_server
        self.tool_proxy_handler.set_ws_server(ws_server)

    def _get_websocket_url(self, local_ip: str, port: int) -> str:
        """获取websocket地址

        Args:
            local_ip: 本地IP地址
            port: 端口号

        Returns:
            str: websocket地址
        """
        server_config = self.config["server"]
        websocket_config = server_config.get("websocket")

        if websocket_config and "你" not in websocket_config:
            return websocket_config
        else:
            return f"ws://{local_ip}:{port}/xiaozhi/v1/"

    async def start(self):
        try:
            server_config = self.config["server"]
            read_config_from_api = self.config.get("read_config_from_api", False)
            host = server_config.get("ip", "0.0.0.0")
            port = int(server_config.get("http_port", 8003))

            if not port:
                self.logger.bind(tag=TAG).warning("HTTP服务器端口未配置，跳过启动")
                return

            app = web.Application()

            if not read_config_from_api:
                # 如果没有开启智控台，只是单模块运行，就需要再添加简单OTA接口，用于下发websocket接口
                app.add_routes(
                    [
                        web.get("/xiaozhi/ota/", self.ota_handler.handle_get),
                        web.post("/xiaozhi/ota/", self.ota_handler.handle_post),
                        web.options(
                            "/xiaozhi/ota/", self.ota_handler.handle_options
                        ),
                        # 下载接口，仅提供 data/bin/*.bin 下载
                        web.get(
                            "/xiaozhi/ota/download/{filename}",
                            self.ota_handler.handle_download,
                        ),
                        web.options(
                            "/xiaozhi/ota/download/{filename}",
                            self.ota_handler.handle_options,
                        ),
                    ]
                )

            # 添加路由
            app.add_routes(
                [
                    web.get("/mcp/vision/explain", self.vision_handler.handle_get),
                    web.post("/mcp/vision/explain", self.vision_handler.handle_post),
                    web.options("/mcp/vision/explain", self.vision_handler.handle_post),
                    # 图片缓存访问接口 - 用于MCP工具服务器获取缓存的图片
                    web.get("/mcp/vision/image/{image_id}", self.vision_handler.handle_get_image),
                    # 内部工具代理接口 - 用于MCP工具服务器代理调用设备端工具
                    web.post("/internal/tool/call", self.tool_proxy_handler.handle_post),
                    web.options("/internal/tool/call", self.tool_proxy_handler.handle_options),
                    web.get("/internal/devices", self.tool_proxy_handler.handle_list_devices),
                ]
            )

            # 运行服务
            self.logger.bind(tag=TAG).info(f"正在启动HTTP服务器: {host}:{port}")
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()
            
            self.logger.bind(tag=TAG).info(f"HTTP服务器已启动: http://{host}:{port}")

            # 保持服务运行
            while True:
                await asyncio.sleep(3600)  # 每隔 1 小时检查一次
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"HTTP服务器启动失败: {e}", exc_info=True)
            raise
