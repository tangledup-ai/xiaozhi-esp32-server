#!/usr/bin/env python3
"""
测试工具代理功能 - 通过HTTP API调用设备端MCP工具

使用方法:
1. 确保 app.py 正在运行且有ESP32设备连接
2. 运行此脚本: python test/test_tool_proxy.py

可选参数:
  --host HOST       HTTP服务器地址 (默认: 127.0.0.1)
  --port PORT       HTTP服务器端口 (默认: 8003)
  --brightness N    设置屏幕亮度 (0-100)
  --volume N        设置音量 (0-100)
  --status          获取设备状态
  --list-devices    列出已连接的设备
  --device-id ID    目标设备ID (可选，不指定则使用第一个可用设备)
"""

import argparse
import asyncio
import json
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp


async def call_tool(base_url: str, tool_name: str, arguments: dict, auth_token: str = None, internal_key: str = None, device_id: str = None):
    """调用工具代理API"""
    url = f"{base_url}/internal/tool/call"
    headers = {"Content-Type": "application/json"}
    if internal_key:
        headers["X-Internal-Key"] = internal_key
    elif auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    
    payload = {
        "tool_name": tool_name,
        "arguments": arguments
    }
    
    # Include device_id in payload if specified
    if device_id:
        payload["device_id"] = device_id
    
    print(f"\n>>> 调用工具: {tool_name}")
    print(f"    参数: {json.dumps(arguments, ensure_ascii=False)}")
    if device_id:
        print(f"    目标设备: {device_id}")
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            result = await response.json()
            print(f"    状态码: {response.status}")
            print(f"    响应: {json.dumps(result, ensure_ascii=False, indent=2)}")
            return result


async def list_devices(base_url: str, auth_token: str = None, internal_key: str = None):
    """列出已连接的设备"""
    url = f"{base_url}/internal/devices"
    headers = {}
    if internal_key:
        headers["X-Internal-Key"] = internal_key
    elif auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    
    print(f"\n>>> 列出已连接的设备")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            result = await response.json()
            print(f"    状态码: {response.status}")
            print(f"    响应: {json.dumps(result, ensure_ascii=False, indent=2)}")
            return result


async def main():
    parser = argparse.ArgumentParser(description="测试工具代理功能")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP服务器地址")
    parser.add_argument("--port", type=int, default=8003, help="HTTP服务器端口")
    parser.add_argument("--brightness", type=int, help="设置屏幕亮度 (0-100)")
    parser.add_argument("--volume", type=int, help="设置音量 (0-100)")
    parser.add_argument("--status", action="store_true", help="获取设备状态")
    parser.add_argument("--list-devices", action="store_true", help="列出已连接的设备")
    parser.add_argument("--device-id", default=None, help="目标设备ID (可选，不指定则使用第一个可用设备)")
    parser.add_argument("--token", default=None, help="JWT认证token (可选)")
    parser.add_argument("--internal-key", default=None, help="内部API密钥 (可选，用于Docker环境)")
    
    args = parser.parse_args()
    base_url = f"http://{args.host}:{args.port}"
    internal_key = args.internal_key
    
    print(f"=== 工具代理测试 ===")
    print(f"目标服务器: {base_url}")
    
    # 如果没有指定任何操作，默认执行所有测试
    run_all = not (args.brightness is not None or args.volume is not None or 
                   args.status or args.list_devices)
    
    try:
        # 列出设备
        if args.list_devices or run_all:
            await list_devices(base_url, args.token, internal_key)
        
        # 获取设备状态
        if args.status or run_all:
            await call_tool(base_url, "self_get_device_status", {}, args.token, internal_key, args.device_id)
        
        # 设置亮度
        if args.brightness is not None:
            await call_tool(
                base_url, 
                "self_screen_set_brightness", 
                {"brightness": args.brightness},
                args.token,
                internal_key,
                args.device_id
            )
        elif run_all:
            # 默认测试：设置亮度为50
            print("\n--- 测试设置亮度为 50 ---")
            await call_tool(
                base_url,
                "self_screen_set_brightness",
                {"brightness": 50},
                args.token,
                internal_key,
                args.device_id
            )
        
        # 设置音量
        if args.volume is not None:
            await call_tool(
                base_url,
                "self_audio_speaker_set_volume",
                {"volume": args.volume},
                args.token,
                internal_key,
                args.device_id
            )
        
        print("\n=== 测试完成 ===")
        
    except aiohttp.ClientConnectorError as e:
        print(f"\n错误: 无法连接到服务器 {base_url}")
        print(f"请确保 app.py 正在运行")
        print(f"详细信息: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
