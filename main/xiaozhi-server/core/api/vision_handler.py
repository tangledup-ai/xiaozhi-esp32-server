import json
import copy
import os
import uuid
from pathlib import Path
from aiohttp import web
from config.logger import setup_logging
from core.utils.util import get_vision_url, get_local_ip, is_valid_image_file
from core.api.base_handler import BaseHandler
from core.utils.util import get_vision_url, is_valid_image_file
from core.utils.vllm import create_instance
from config.config_loader import get_private_config_from_api
from core.utils.auth import AuthToken
import base64
from typing import Tuple, Optional
from plugins_func.register import Action

TAG = __name__

# 设置最大文件大小为5MB
MAX_FILE_SIZE = 5 * 1024 * 1024

# 图片缓存目录
IMAGE_CACHE_DIR = Path("tmp/image_cache")
IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class VisionHandler(BaseHandler):
    def __init__(self, config: dict):
        super().__init__(config)
        # 初始化认证工具
        self.auth = AuthToken(config["server"]["auth_key"])

    def _create_error_response(self, message: str) -> dict:
        """创建统一的错误响应格式"""
        return {"success": False, "message": message}

    def _verify_auth_token(self, request) -> Tuple[bool, Optional[str]]:
        """验证认证token"""
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False, None

        token = auth_header[7:]  # 移除"Bearer "前缀
        return self.auth.verify_token(token)

    async def handle_post(self, request):
        """处理 MCP Vision POST 请求"""
        response = None  # 初始化response变量
        try:
            # 验证token
            is_valid, token_device_id = self._verify_auth_token(request)
            if not is_valid:
                response = web.Response(
                    text=json.dumps(
                        self._create_error_response("无效的认证token或token已过期")
                    ),
                    content_type="application/json",
                    status=401,
                )
                return response

            # 获取请求头信息
            device_id = request.headers.get("Device-Id", "")
            client_id = request.headers.get("Client-Id", "")
            if device_id != token_device_id:
                raise ValueError("设备ID与token不匹配")
            # 解析multipart/form-data请求
            reader = await request.multipart()

            # 读取question字段
            question_field = await reader.next()
            if question_field is None:
                raise ValueError("缺少问题字段")
            question = await question_field.text()
            self.logger.bind(tag=TAG).debug(f"Question: {question}")

            # 读取图片文件
            image_field = await reader.next()
            if image_field is None:
                raise ValueError("缺少图片文件")

            # 读取图片数据
            image_data = await image_field.read()
            if not image_data:
                raise ValueError("图片数据为空")

            # 检查文件大小
            if len(image_data) > MAX_FILE_SIZE:
                raise ValueError(
                    f"图片大小超过限制，最大允许{MAX_FILE_SIZE/1024/1024}MB"
                )

            # 检查文件格式
            if not is_valid_image_file(image_data):
                raise ValueError(
                    "不支持的文件格式，请上传有效的图片文件（支持JPEG、PNG、GIF、BMP、TIFF、WEBP格式）"
                )

            # 保存图片到缓存目录，生成唯一ID
            image_id = str(uuid.uuid4())
            image_path = IMAGE_CACHE_DIR / f"{image_id}.jpg"
            image_path.write_bytes(image_data)
            self.logger.bind(tag=TAG).debug(f"Image cached: {image_path}")

            # 构建图片访问URL
            server_config = self.config.get("server", {})
            vision_explain = server_config.get("vision_explain", "")
            if vision_explain and "你的" not in vision_explain:
                # 从配置的vision_explain URL中提取基础URL
                base_url = vision_explain.rsplit("/mcp/vision/explain", 1)[0]
            else:
                # 使用本地IP和端口构建URL
                local_ip = get_local_ip()
                port = int(server_config.get("http_port", 8003))
                base_url = f"http://{local_ip}:{port}"
            
            # 支持通过环境变量覆盖图片基础URL（用于Docker环境）
            # 当MCP工具服务器在Docker容器内运行时，需要使用容器可访问的地址
            # image_base_url = os.environ.get(
            #     "IMAGE_BASE_URL",
            #     server_config.get("image_base_url", base_url)
            # )
            
            # image_url = f"{image_base_url}/mcp/vision/image/{image_id}"
            image_url = f"{base_url}/mcp/vision/image/{image_id}"

            # 将图片转换为base64编码
            image_base64 = base64.b64encode(image_data).decode("utf-8")

            # 如果开启了智控台，则从智控台获取模型配置
            current_config = copy.deepcopy(self.config)
            read_config_from_api = current_config.get("read_config_from_api", False)
            if read_config_from_api:
                current_config = await get_private_config_from_api(
                    current_config,
                    device_id,
                    client_id,
                )

            select_vllm_module = current_config["selected_module"].get("VLLM")
            if not select_vllm_module:
                raise ValueError("您还未设置默认的视觉分析模块")

            vllm_type = (
                select_vllm_module
                if "type" not in current_config["VLLM"][select_vllm_module]
                else current_config["VLLM"][select_vllm_module]["type"]
            )

            if not vllm_type:
                raise ValueError(f"无法找到VLLM模块对应的供应器{vllm_type}")

            vllm = create_instance(
                vllm_type, current_config["VLLM"][select_vllm_module]
            )

            # result = vllm.response(question, image_base64)
            result = ""

            return_json = {
                "success": True,
                "action": Action.NONE.name,
                "response": result,
                "image_url": image_url,  # Include image URL for MCP tool server to fetch
            }

            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        except ValueError as e:
            self.logger.bind(tag=TAG).error(f"MCP Vision POST请求异常: {e}")
            return_json = self._create_error_response(str(e))
            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"MCP Vision POST请求异常: {e}")
            return_json = self._create_error_response("处理请求时发生错误")
            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        finally:
            if response:
                self._add_cors_headers(response)
            return response

    async def handle_get(self, request):
        """处理 MCP Vision GET 请求"""
        try:
            vision_explain = get_vision_url(self.config)
            if vision_explain and len(vision_explain) > 0 and "null" != vision_explain:
                message = (
                    f"MCP Vision 接口运行正常，视觉解释接口地址是：{vision_explain}"
                )
            else:
                message = "MCP Vision 接口运行不正常，请打开data目录下的.config.yaml文件，找到【server.vision_explain】，设置好地址"

            response = web.Response(text=message, content_type="text/plain")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"MCP Vision GET请求异常: {e}")
            return_json = self._create_error_response("服务器内部错误")
            response = web.Response(
                text=json.dumps(return_json, separators=(",", ":")),
                content_type="application/json",
            )
        finally:
            self._add_cors_headers(response)
            return response

    def _add_cors_headers(self, response):
        """添加CORS头信息"""
        response.headers["Access-Control-Allow-Headers"] = (
            "client-id, content-type, device-id"
        )
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Origin"] = "*"

    async def handle_get_image(self, request):
        """提供缓存图片的访问"""
        response = None
        try:
            image_id = request.match_info.get('image_id', '')
            if not image_id:
                raise ValueError("缺少图片ID")
            
            # 安全检查：确保image_id是有效的UUID格式，防止路径遍历攻击
            try:
                uuid.UUID(image_id)
            except ValueError:
                raise ValueError("无效的图片ID格式")
            
            image_path = IMAGE_CACHE_DIR / f"{image_id}.jpg"
            if not image_path.exists():
                response = web.Response(
                    text=json.dumps({"success": False, "message": "图片不存在或已过期"}),
                    content_type="application/json",
                    status=404,
                )
                return response
            
            image_data = image_path.read_bytes()
            response = web.Response(
                body=image_data,
                content_type="image/jpeg",
            )
        except ValueError as e:
            self.logger.bind(tag=TAG).error(f"获取缓存图片异常: {e}")
            response = web.Response(
                text=json.dumps({"success": False, "message": str(e)}),
                content_type="application/json",
                status=400,
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"获取缓存图片异常: {e}")
            response = web.Response(
                text=json.dumps({"success": False, "message": "服务器内部错误"}),
                content_type="application/json",
                status=500,
            )
        finally:
            if response:
                self._add_cors_headers(response)
            return response
