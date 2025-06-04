#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIcarus Napcat Adapter v1.4.0 配置检查脚本
用于验证 v1.4.0 协议的安装和配置是否正确
"""

import sys
import os
from pathlib import Path

# 将项目根目录添加到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def check_protocol_installation():
    """检查 AIcarus-Message-Protocol v1.4.0 是否正确安装"""
    print("🔍 检查 AIcarus-Message-Protocol 安装...")
    
    try:
        import aicarus_protocols
        print(f"  ✅ aicarus_protocols 已安装")
        
        # 检查版本
        from aicarus_protocols import PROTOCOL_VERSION
        print(f"  📋 协议版本: {PROTOCOL_VERSION}")
        
        if PROTOCOL_VERSION == "1.4.0":
            print("  ✅ 协议版本正确 (v1.4.0)")
        else:
            print(f"  ⚠️  协议版本不匹配，期望 1.4.0，实际 {PROTOCOL_VERSION}")
            return False
            
        # 检查关键类
        try:
            from aicarus_protocols import (
                Event,
                UserInfo,
                ConversationInfo,
                Seg,
                SegBuilder,
                EventBuilder,
                EventType,
                ConversationType,
            )
            print("  ✅ 所有关键类可以正常导入")
            return True
        except ImportError as e:
            print(f"  ❌ 关键类导入失败: {e}")
            return False
            
    except ImportError as e:
        print(f"  ❌ aicarus_protocols 未安装或安装错误: {e}")
        print("  💡 请运行: pip install -e path/to/AIcarus-Message-Protocol")
        return False

def check_adapter_files():
    """检查 v1.4.0 适配器文件是否存在"""
    print("\n🔍 检查 v1.4.0 适配器文件...")
    
    required_files = [
        "src/recv_handler_aicarus_v1_4_0.py",
        "src/send_handler_aicarus_v1_4_0.py",
        "src/aic_com_layer_v1_4_0.py",
        "src/main_aicarus_v1_4_0.py",
        "src/napcat_definitions_v1_4_0.py",
        "run_adapter_v1_4_0.py",
    ]
    
    all_exist = True
    for file_path in required_files:
        full_path = project_root / file_path
        if full_path.exists():
            print(f"  ✅ {file_path}")
        else:
            print(f"  ❌ {file_path} 不存在")
            all_exist = False
    
    return all_exist

def check_imports():
    """检查 v1.4.0 文件的导入是否正常"""
    print("\n🔍 检查 v1.4.0 文件导入...")
    
    test_modules = [
        "src.recv_handler_aicarus_v1_4_0",
        "src.send_handler_aicarus_v1_4_0", 
        "src.aic_com_layer_v1_4_0",
        "src.napcat_definitions_v1_4_0",
    ]
    
    all_imported = True
    for module_name in test_modules:
        try:
            __import__(module_name)
            print(f"  ✅ {module_name}")
        except ImportError as e:
            print(f"  ❌ {module_name} 导入失败: {e}")
            all_imported = False
        except Exception as e:
            print(f"  ⚠️  {module_name} 导入时出现其他错误: {e}")
            all_imported = False
    
    return all_imported

def check_config():
    """检查配置文件"""
    print("\n🔍 检查配置文件...")
    
    config_file = project_root / "config.toml"
    template_file = project_root / "template" / "config_template.toml"
    
    if template_file.exists():
        print(f"  ✅ 配置模板存在: {template_file}")
    else:
        print(f"  ❌ 配置模板不存在: {template_file}")
        return False
    
    if config_file.exists():
        print(f"  ✅ 配置文件存在: {config_file}")
        try:
            from src.config import get_config
            config = get_config()
            print(f"  📋 Core 连接地址: {config.core_connection_url}")
            print(f"  📋 Platform ID: {config.core_platform_id}")
            print(f"  📋 Napcat 监听端口: {config.adapter_server_port}")
            return True
        except Exception as e:
            print(f"  ⚠️  配置文件解析失败: {e}")
            return False
    else:
        print(f"  ⚠️  配置文件不存在: {config_file}")
        print("  💡 首次运行时会自动创建")
        return True

def test_event_creation():
    """测试事件创建"""
    print("\n🔍 测试 v1.4.0 事件创建...")
    
    try:
        from aicarus_protocols import Event, SegBuilder, UserInfo, ConversationInfo, ConversationType
        import time
        import uuid
        
        # 创建测试事件
        test_event = Event(
            event_id=f"test_{uuid.uuid4()}",
            event_type="message.group.normal",
            time=time.time() * 1000,
            platform="napcat_test",
            bot_id="test_bot",
            user_info=UserInfo(
                platform="qq",
                user_id="12345",
                user_nickname="测试用户"  # 修复：使用 user_nickname
            ),
            conversation_info=ConversationInfo(
                conversation_id="67890",
                type=ConversationType.GROUP,
                platform="qq",
                name="测试群组"
            ),
            content=[
                SegBuilder.text("Hello, World!"),
            ],
            raw_data='{"test": true}'
        )
        
        # 测试序列化和反序列化
        event_dict = test_event.to_dict()
        restored_event = Event.from_dict(event_dict)
        
        if test_event.event_id == restored_event.event_id:
            print("  ✅ 事件创建和序列化测试通过")
            return True
        else:
            print("  ❌ 事件序列化测试失败")
            return False
            
    except Exception as e:
        print(f"  ❌ 事件创建测试失败: {e}")
        return False

def main():
    """主检查函数"""
    print("🚀 AIcarus Napcat Adapter v1.4.0 配置检查")
    print("=" * 50)
    
    checks = [
        ("协议安装", check_protocol_installation),
        ("适配器文件", check_adapter_files),
        ("模块导入", check_imports),
        ("配置文件", check_config),
        ("事件创建", test_event_creation),
    ]
    
    results = []
    for check_name, check_func in checks:
        try:
            result = check_func()
            results.append((check_name, result))
        except Exception as e:
            print(f"  ❌ {check_name} 检查时发生异常: {e}")
            results.append((check_name, False))
    
    print("\n" + "=" * 50)
    print("📊 检查结果汇总:")
    
    all_passed = True
    for check_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {check_name}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 所有检查通过！v1.4.0 适配器已准备就绪。")
        print("💡 启动命令: python run_adapter_v1_4_0.py")
        return 0
    else:
        print("⚠️  部分检查未通过，请根据上述信息修复问题。")
        print("💡 如需帮助，请参考 MIGRATION_TO_V1.4.0.md")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)