# 认证使用指南

## 概述

本项目支持两种认证方式：
1. **JWT Token** - 适用于需要过期时间控制的场景
2. **Internal API Key** - 适用于服务间通信的简单场景

---

## 1. 工具代理 API 认证 (test_tool_proxy.py)

### 方式一：使用 JWT Token

**生成 Token:**
```bash
# 默认24小时有效期
python generate_token.py --device-id "my-client"

# 自定义有效期
python generate_token.py --device-id "my-client" --expire-hours 168  # 7天
python generate_token.py --device-id "my-client" --expire-hours 0.5  # 30分钟
python generate_token.py --device-id "my-client" --expire-hours 720  # 30天
```

**使用 Token:**
```bash
python test/test_tool_proxy.py --brightness 100 --host 6.6.6.78 --token "YOUR_TOKEN_HERE"
```

### 方式二：使用 Internal API Key

**配置 (在 data/.config.yaml 中):**
```yaml
server:
  internal_api_key: "your-secret-key-here"
```

**使用:**
```bash
python test/test_tool_proxy.py --brightness 100 --host 6.6.6.78 --internal-key "your-secret-key-here"
```

---

## 2. MCP 客户端认证 (test_mcp_langchain.py)

**注意:** MCP 工具服务器 (mcp_tool_server.py) 默认不需要客户端认证，但支持传递认证头以备将来使用。

### 使用 Token (可选):

```bash
# 生成 token
python generate_token.py --device-id "mcp-client"

# 使用 LangChain 客户端
python test/test_mcp_langchain.py --list --token "YOUR_TOKEN_HERE"

# 使用原生 MCP 客户端
python test/test_mcp_langchain.py --list --native --token "YOUR_TOKEN_HERE"

# 调用工具
python test/test_mcp_langchain.py --call self_screen_set_brightness --args '{"brightness": 50}' --token "YOUR_TOKEN_HERE"
```

### 代码中使用 (LangChain):

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

mcp_config = {
    "xiaozhi": {
        "url": "http://127.0.0.1:8805/sse",
        "transport": "sse",
        "headers": {
            "Authorization": "Bearer YOUR_TOKEN_HERE"
        }
    }
}

client = MultiServerMCPClient(mcp_config)
tools = await client.get_tools()
```

### 代码中使用 (原生 MCP):

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

url = "http://127.0.0.1:8805/sse"
headers = {"Authorization": "Bearer YOUR_TOKEN_HERE"}

async with sse_client(url, headers=headers) as (read_stream, write_stream):
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        tools_result = await session.list_tools()
```

---

## 3. 认证配置说明

### auth_key 来源

系统会按以下优先级获取 `auth_key`:

1. `manager-api.secret` (推荐，在 data/.config.yaml 中配置)
2. `server.auth_key` (在 config.yaml 中配置)
3. 如果都未配置，系统会自动生成随机密钥

### 当前配置查看

启动 `app.py` 时，系统会自动使用配置的密钥。你可以在 `data/.config.yaml` 中查看：

```yaml
manager-api:
  secret: 91e44df8-a834-4ce6-a278-2c6b6c15fba3  # 这就是你的 auth_key
```

---

## 4. 常见问题

**Q: device_id 必须是 IP 地址吗？**
A: 不需要，可以是任意字符串标识符，如 "my-client"、"test-device" 等。

**Q: Token 过期了怎么办？**
A: 重新运行 `generate_token.py` 生成新的 token。

**Q: Internal API Key 和 JWT Token 有什么区别？**
A: 
- Internal API Key: 永久有效，适合服务间通信
- JWT Token: 有过期时间，更安全，适合临时访问

**Q: MCP 工具服务器需要认证吗？**
A: 默认不需要。MCP 工具服务器是本地服务，但它在调用设备工具时会自动生成 token 访问工具代理 API。

---

## 5. 安全建议

1. **生产环境**: 使用 JWT Token 并设置合理的过期时间
2. **开发环境**: 可以使用 Internal API Key 简化开发
3. **密钥管理**: 不要将密钥提交到版本控制系统
4. **网络隔离**: 如果可能，将 MCP 工具服务器限制在本地网络访问
