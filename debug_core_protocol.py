#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试 Core 协议兼容性
"""

import asyncio
import websockets
import json
import time
import sys
import os
import uuid

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config import get_config

async def test_protocol_compatibility():
    """测试协议兼容性"""
    config = get_config()
    core_url = config.core_connection_url
    platform_id = config.core_platform_id
    
    print(f"=== AIcarus 协议兼容性测试 ===")
    print(f"Core URL: {core_url}")
    print(f"Platform ID: {platform_id}")
    
    try:
        websocket = await websockets.connect(core_url)
        print("✅ WebSocket 连接成功!")
        
        # 测试1: 发送标准的 meta.lifecycle.connect 事件
        print("\n📤 测试1: 发送 meta.lifecycle.connect 事件")
        connect_event = {
            "event_id": f"meta_connect_{uuid.uuid4()}",
            "event_type": "meta.lifecycle.connect",
            "time": time.time() * 1000,
            "platform": platform_id,
            "bot_id": platform_id,
            "user_info": None,
            "conversation_info": None,
            "content": [{
                "type": "meta.lifecycle",
                "data": {
                    "lifecycle_type": "connect",
                    "details": {
                        "adapter_platform": "napcat",
                        "adapter_version": "0.1.0",
                        "protocol_version": "1.4.0"
                    }
                }
            }],
            "raw_data": json.dumps({"source": "adapter_test"})
        }
        
        await websocket.send(json.dumps(connect_event, ensure_ascii=False))
        print("✅ connect 事件已发送")
        
        # 等待可能的响应
        try:
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            print(f"📥 收到响应: {response}")
        except asyncio.TimeoutError:
            print("⚠️ 连接事件无响应 (这可能是正常的)")
        
        # 测试2: 发送模拟消息事件
        print("\n📤 测试2: 发送模拟消息事件")
        message_event = {
            "event_id": f"message_test_{uuid.uuid4()}",
            "event_type": "message.group.normal",
            "time": time.time() * 1000,
            "platform": platform_id,
            "bot_id": platform_id,
            "user_info": {
                "platform": platform_id,
                "user_id": "123456789",
                "user_nickname": "测试用户",
                "user_cardname": None,
                "user_titlename": None,
                "permission_level": "member",
                "role": "member",
                "additional_data": {}
            },
            "conversation_info": {
                "platform": platform_id,
                "conversation_id": "987654321",
                "type": "group",
                "name": "测试群"
            },
            "content": [
                {
                    "type": "message.metadata",
                    "data": {
                        "message_id": "test_msg_001"
                    }
                },
                {
                    "type": "text",
                    "data": {
                        "text": "这是一条测试消息"
                    }
                }
            ],
            "raw_data": json.dumps({"test": "message_event"})
        }
        
        await websocket.send(json.dumps(message_event, ensure_ascii=False))
        print("✅ 消息事件已发送")
        
        # 等待响应
        try:
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            print(f"📥 收到响应: {response}")
        except asyncio.TimeoutError:
            print("⚠️ 消息事件无响应")
        
        # 测试3: 发送心跳事件
        print("\n📤 测试3: 发送心跳事件")
        heartbeat_event = {
            "event_id": f"meta_heartbeat_{uuid.uuid4()}",
            "event_type": "meta.heartbeat",
            "time": time.time() * 1000,
            "platform": platform_id,
            "bot_id": platform_id,
            "user_info": None,
            "conversation_info": None,
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
        
        await websocket.send(json.dumps(heartbeat_event, ensure_ascii=False))
        print("✅ 心跳事件已发送")
        
        # 等待响应
        try:
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            print(f"📥 收到响应: {response}")
        except asyncio.TimeoutError:
            print("⚠️ 心跳事件无响应")
        
        # 测试4: 监听是否有 Core 主动发送的消息
        print("\n⏳ 测试4: 监听 Core 主动消息 (10秒)")
        for i in range(10):
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                print(f"📥 收到主动消息: {response}")
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(1)
        
        print("✅ 协议测试完成")
        await websocket.close()
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_protocol_compatibility())
