#!/usr/bin/env python3
"""
测试通过LangChain MCP客户端获取和调用工具

使用方法:
1. 确保 app.py 正在运行且有ESP32设备连接
2. 启动 mcp_tool_server.py: python core/mcp_tool_server.py
3. 运行此脚本: python test/test_mcp_langchain.py

可选参数:
  --host HOST       MCP服务器地址 (默认: 127.0.0.1)
  --port PORT       MCP服务器端口 (默认: 8805)
  --list            仅列出工具
  --call TOOL       调用指定工具
  --args JSON       工具参数 (JSON格式)
  --token TOKEN     认证Token (可选，用于需要认证的MCP服务器)
  --native          使用原生MCP客户端而非LangChain
"""

import argparse
import asyncio
import json
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_with_langchain_mcp(url: str, list_only: bool = True, tool_name: str = None, tool_args: dict = None, auth_token: str = None):
    """使用langchain-mcp-adapters测试MCP服务器"""
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        print("错误: 请安装 langchain-mcp-adapters")
        print("  pip install langchain-mcp-adapters")
        return False

    # 配置MCP服务器
    mcp_config = {
        "xiaozhi": {
            "url": url,
            "transport": "sse"
        }
    }
    
    # 如果提供了认证token，添加到配置中
    if auth_token:
        mcp_config["xiaozhi"]["headers"] = {
            "Authorization": f"Bearer {auth_token}"
        }
    
    print(f">>> 连接到MCP服务器: {url}")
    print(f"    配置: {json.dumps(mcp_config, indent=2)}")
    
    try:
        # 新版API不使用context manager
        client = MultiServerMCPClient(mcp_config)
        
        # 获取工具列表
        tools = await client.get_tools()
        
        print(f"\n>>> 获取到 {len(tools)} 个工具:")
        for i, tool in enumerate(tools, 1):
            print(f"    {i}. {tool.name}")
            if hasattr(tool, 'description') and tool.description:
                # 只显示描述的第一行
                desc = tool.description.split('\n')[0][:60]
                print(f"       {desc}...")
        
        if list_only:
            return True
        
        # 调用指定工具
        if tool_name:
            print(f"\n>>> 调用工具: {tool_name}")
            print(f"    参数: {json.dumps(tool_args or {}, ensure_ascii=False)}")
            
            # 查找工具
            target_tool = None
            for tool in tools:
                if tool.name == tool_name:
                    target_tool = tool
                    break
            
            if not target_tool:
                print(f"    错误: 工具 '{tool_name}' 不存在")
                return False
            
            # 调用工具
            result = await target_tool.ainvoke(tool_args or {})
            print(f"    结果: {result}")
            return True
        
        return True
            
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_with_mcp_client(url: str, list_only: bool = True, tool_name: str = None, tool_args: dict = None, auth_token: str = None):
    """使用原生mcp客户端测试MCP服务器"""
    try:
        from mcp import ClientSession
        from mcp.client.sse import sse_client
    except ImportError:
        print("错误: 请安装 mcp")
        print("  pip install mcp")
        return False
    
    print(f">>> 连接到MCP服务器 (原生客户端): {url}")
    
    # 准备headers
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    
    try:
        async with sse_client(url, headers=headers if headers else None) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # 初始化
                await session.initialize()
                
                # 获取工具列表
                tools_result = await session.list_tools()
                tools = tools_result.tools
                
                print(f"\n>>> 获取到 {len(tools)} 个工具:")
                for i, tool in enumerate(tools, 1):
                    print(f"    {i}. {tool.name}")
                    if tool.description:
                        desc = tool.description.split('\n')[0][:60]
                        print(f"       {desc}...")
                
                if list_only:
                    return True
                
                # 调用指定工具
                if tool_name:
                    print(f"\n>>> 调用工具: {tool_name}")
                    print(f"    参数: {json.dumps(tool_args or {}, ensure_ascii=False)}")
                    
                    result = await session.call_tool(tool_name, tool_args or {})
                    print(f"    结果: {result}")
                    return True
                
                return True
                
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    parser = argparse.ArgumentParser(description="测试LangChain MCP客户端")
    parser.add_argument("--host", default="127.0.0.1", help="MCP服务器地址")
    parser.add_argument("--port", type=int, default=8805, help="MCP服务器端口")
    parser.add_argument("--list", action="store_true", help="仅列出工具")
    parser.add_argument("--call", dest="tool_name", help="调用指定工具")
    parser.add_argument("--args", dest="tool_args", help="工具参数 (JSON格式)")
    parser.add_argument("--native", action="store_true", help="使用原生MCP客户端而非LangChain")
    parser.add_argument("--token", help="认证Token (可选)")
    
    args = parser.parse_args()
    
    url = f"http://{args.host}:{args.port}/sse"
    list_only = args.list or not args.tool_name
    
    tool_args = None
    if args.tool_args:
        try:
            tool_args = json.loads(args.tool_args)
        except json.JSONDecodeError:
            print(f"错误: 无效的JSON参数: {args.tool_args}")
            sys.exit(1)
    
    print("=== MCP工具测试 ===")
    print(f"服务器URL: {url}")
    if args.token:
        print(f"使用认证Token: {args.token[:20]}...")
    
    if args.native:
        success = await test_with_mcp_client(url, list_only, args.tool_name, tool_args, args.token)
    else:
        success = await test_with_langchain_mcp(url, list_only, args.tool_name, tool_args, args.token)
    
    print("\n=== 测试完成 ===")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    # NOTE: sample call python test/test_mcp_langchain.py --call self_screen_set_brightness --args '{"brightness": 50}'
    asyncio.run(main())
