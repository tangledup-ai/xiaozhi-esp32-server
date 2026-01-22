#!/usr/bin/env python3
"""
生成认证Token工具

使用方法:
python generate_token.py --device-id "your-device-id"
"""

import argparse
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.utils.auth import AuthToken
from config.settings import load_config


def main():
    parser = argparse.ArgumentParser(description="生成认证Token")
    parser.add_argument("--device-id", default="test-device", help="设备ID (默认: test-device)")
    parser.add_argument("--auth-key", help="认证密钥 (如果不提供，将从配置中读取); see 'internal_api_key' in server or 'secret' in main/xiaozhi-server/data/.config.yaml")
    parser.add_argument(
        "--expire-hours",
        type=float,
        default=24.0,
        help="Token有效期（小时），默认24小时。可以使用小数，如0.5表示30分钟，168表示7天",
    )
    
    args = parser.parse_args()
    
    # 获取auth_key
    auth_key = args.auth_key
    
    if not auth_key:
        # 加载配置
        config = load_config()
        
        # 尝试从manager-api.secret获取（与app.py逻辑一致）
        auth_key = config.get("manager-api", {}).get("secret", "")
        
        if not auth_key or len(auth_key) == 0 or "你" in auth_key:
            # 尝试从server.auth_key获取
            auth_key = config.get("server", {}).get("auth_key", "")
        
        if not auth_key or len(auth_key) == 0 or "你" in auth_key:
            print("错误: 配置中没有找到 auth_key")
            print("\n解决方案:")
            print("1. 使用 --auth-key 参数直接指定:")
            print("   python generate_token.py --device-id your-device --auth-key your-secret")
            print("\n2. 或在 data/.config.yaml 中配置 manager-api.secret")
            print("\n3. 或在 config.yaml 中添加:")
            print("   server:")
            print("     auth_key: your-secret-key-here")
            sys.exit(1)
    
    # 生成token
    auth = AuthToken(auth_key)
    token = auth.generate_token(args.device_id, args.expire_hours)
    
    # 计算过期时间的友好显示
    if args.expire_hours < 1:
        expire_display = f"{int(args.expire_hours * 60)}分钟"
    elif args.expire_hours == 24:
        expire_display = "1天"
    elif args.expire_hours % 24 == 0:
        expire_display = f"{int(args.expire_hours / 24)}天"
    else:
        expire_display = f"{args.expire_hours}小时"
    
    print(f"\n=== 认证Token生成成功 ===")
    print(f"设备ID: {args.device_id}")
    print(f"Auth Key: {auth_key}")
    print(f"有效期: {expire_display}")
    print(f"\nToken:")
    print(token)
    print(f"\n=== 使用方法 ===")
    print(f"1. 使用 --token 参数:")
    print(f"   python test/test_tool_proxy.py --brightness 100 --host 6.6.6.78 --token {token}")
    print(f"\n2. 或者在请求头中添加:")
    print(f"   Authorization: Bearer {token}")
    print(f"\n=== 自定义有效期示例 ===")
    print(f"30分钟: python generate_token.py --device-id {args.device_id} --expire-hours 0.5")
    print(f"7天:    python generate_token.py --device-id {args.device_id} --expire-hours 168")
    print(f"30天:   python generate_token.py --device-id {args.device_id} --expire-hours 720")
    

if __name__ == "__main__":
    main()
