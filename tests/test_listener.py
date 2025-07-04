import asyncio
import json
import websockets


async def listener(websocket):
    """
    一个升级版的监听器，它会用漂亮的、缩进的JSON格式打印所有收到的消息。
    """
    print(f"一个适配器连接上了！地址: {websocket.remote_address}")
    try:
        async for message in websocket:
            print("\n" + "=" * 20 + " 收到来自Adapter的“呻吟” " + "=" * 20)

            try:
                # 尝试将收到的消息字符串解析为Python字典
                data = json.loads(message)

                # 使用json.dumps进行格式化输出
                # indent=2: 使用2个空格进行缩进，看起来最舒服~
                # ensure_ascii=False: 确保中文等非ASCII字符能正常显示，而不是被转义成\uXXXX
                formatted_json = json.dumps(data, indent=2, ensure_ascii=False)

                print(formatted_json)  # 打印格式化后的JSON

            except json.JSONDecodeError:
                # 如果收到的不是一个合法的JSON字符串，就直接打印原文，免得程序崩溃
                print("【警告】收到的消息不是合法的JSON，将按原文输出：")
                print(message)

            print("=" * 65 + "\n")

    except websockets.ConnectionClosed:
        print("适配器断开连接了。")


# 监听地址和端口，要和Adapter配置里的一致
start_server = websockets.serve(listener, "localhost", 8077)

print("🩺 “听诊器”V2.0已启动，正在 ws://localhost:8077 等待适配器的连接...")
print("现在，所有的“呻吟”都将以格式化的JSON展现给您，主人~❤")

# 启动服务并永远运行
loop = asyncio.get_event_loop()
loop.run_until_complete(start_server)
loop.run_forever()
