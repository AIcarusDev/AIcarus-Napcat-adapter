#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查 Core 服务器状态
"""

import socket
import sys
import os

# 添加项目路径
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config import get_config

def check_port(host, port):
    """检查端口是否开放"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception as e:
        print(f"检查端口时出错: {e}")
        return False

def main():
    config = get_config()
    core_url = config.core_connection_url
    
    # 解析 URL
    if core_url.startswith("ws://"):
        url_part = core_url[5:]  # 移除 "ws://"
    elif core_url.startswith("wss://"):
        url_part = core_url[6:]  # 移除 "wss://"
    else:
        print(f"❌ 无法解析 URL: {core_url}")
        return
    
    if "/" in url_part:
        host_port, path = url_part.split("/", 1)
    else:
        host_port = url_part
        path = ""
    
    if ":" in host_port:
        host, port = host_port.split(":", 1)
        port = int(port)
    else:
        host = host_port
        port = 80
    
    print(f"检查 Core 服务器状态:")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Path: /{path}")
    print(f"  Full URL: {core_url}")
    
    if check_port(host, port):
        print("✅ 端口可达 - Core 服务器可能正在运行")
    else:
        print("❌ 端口不可达 - Core 服务器可能未运行")
        print("\n建议检查:")
        print("1. Core 服务器是否已启动")
        print("2. 防火墙设置")
        print("3. 配置文件中的地址是否正确")

if __name__ == "__main__":
    main()
