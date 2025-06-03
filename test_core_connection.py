#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试与 Core 的连接
"""

import asyncio
import websockets
import json
import time
import sys
import os

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config import get_config

async def test_core_connection():
    """测试与 Core 的连接"""
    config = get_config()
    core_url = config.core_connection_url
    platform_id = config.core_platform_id
    
    print(f"正在测试连接到: {core_url}")
    print(f"Platform ID: {platform_id}")
    
    try:
        # 尝试连接
        websocket = await websockets.connect(core_url)
        print("✅ 连接成功!")
        
        # 发送测试消息
        test_message = {
            "event_id": "test_connection_001",
            "event_type": "meta.lifecycle.connect",
            "time": time.time() * 1000,
            "platform": platform_id,
            "bot_id": platform_id,
            "content": [{
                "type": "meta.lifecycle",
                "data": {
                    "lifecycle_type": "connect",
                    "details": {
                        "adapter_platform": "napcat",
                        "adapter_version": "0.1.0",
                        "protocol_version": "1.4.0",
                        "test": True
                    }
                }
            }],
            "raw_data": json.dumps({"test": "connection"})
        }
        
        print("📤 发送测试消息...")
        await websocket.send(json.dumps(test_message, ensure_ascii=False))
        print("✅ 消息发送成功!")
        
        # 等待响应
        print("⏳ 等待响应...")
        try:
            response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            print(f"📥 收到响应: {response}")
        except asyncio.TimeoutError:
            print("⚠️ 等待响应超时")
        
        # 保持连接一段时间
        print("🔄 保持连接 30 秒...")
        try:
            for i in range(6):
                await asyncio.sleep(5)
                print(f"   连接状态: {'正常' if websocket.open else '已断开'}")
                if not websocket.open:
                    break
                    
                # 发送心跳
                heartbeat = {
                    "event_id": f"test_heartbeat_{i}",
                    "event_type": "meta.heartbeat",
                    "time": time.time() * 1000,
                    "platform": platform_id,
                    "bot_id": platform_id,
                    "content": [{
                        "type": "meta.heartbeat",
                        "data": {
                            "status_object": {"online": True, "good": True},
                            "interval_ms": 30000,
                            "is_online": True
                        }
                    }],
                    "raw_data": json.dumps({"test": "heartbeat"})
                }
                await websocket.send(json.dumps(heartbeat, ensure_ascii=False))
                print(f"   发送心跳 {i+1}")
                
        except Exception as e:
            print(f"❌ 连接过程中出错: {e}")
        
        # 关闭连接
        await websocket.close()
        print("🔚 连接已关闭")
        
    except ConnectionRefusedError:
        print("❌ 连接被拒绝 - Core 服务器可能未运行")
        return False
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return False
        
    return True

if __name__ == "__main__":
    print("=== Core 连接测试 ===")
    result = asyncio.run(test_core_connection())
    if result:
        print("✅ 测试通过")
    else:
        print("❌ 测试失败")
