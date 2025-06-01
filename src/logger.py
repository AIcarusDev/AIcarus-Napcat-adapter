# aicarus_napcat_adapter/src/logger.py
import sys
import os
from pathlib import Path
from loguru import logger as loguru_logger

# --- 日志配置 ---

# 尝试从环境变量获取日志级别，如果未设置，则使用默认值
# 控制台日志级别：可以设置为 "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
CONSOLE_LOG_LEVEL = os.getenv("ADAPTER_CONSOLE_LOG_LEVEL", "INFO").upper()
# 文件日志级别
FILE_LOG_LEVEL = os.getenv("ADAPTER_FILE_LOG_LEVEL", "DEBUG").upper()

# 日志文件存放目录 (相对于项目根目录的 logs/adapter/ 文件夹)
# 假设 logger.py 在 src 目录下，src 的父目录是项目根目录
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "adapter"
LOG_DIR.mkdir(parents=True, exist_ok=True)  # 确保目录存在

# 日志文件名格式
LOG_FILE_FORMAT = "{time:YYYY-MM-DD}.log"

# 日志轮转设置 (例如，每天0点创建一个新文件)
LOG_ROTATION = "00:00"
# 日志保留时长 (例如，保留最近7天的日志)
LOG_RETENTION = "7 days"
# 日志压缩格式
LOG_COMPRESSION = "zip"

# --- Loguru 配置 ---

# 移除 loguru 默认的处理器，以便完全自定义
loguru_logger.remove()

# 添加控制台输出处理器
loguru_logger.add(
    sys.stderr,  # 输出到标准错误流
    level=CONSOLE_LOG_LEVEL,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    ),
    colorize=True,  # 启用颜色输出
    enqueue=True,  # 异步安全
)

# 添加文件输出处理器
loguru_logger.add(
    LOG_DIR / LOG_FILE_FORMAT,  # 日志文件路径
    level=FILE_LOG_LEVEL,
    format=(
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
        "{level: <8} | "
        "{name}:{function}:{line} - "  # 文件中通常不需要颜色，但可以保留模块信息
        "{message}"
    ),
    rotation=LOG_ROTATION,
    retention=LOG_RETENTION,
    compression=LOG_COMPRESSION,
    encoding="utf-8",  # 确保中文等字符正确写入
    enqueue=True,  # 异步安全
    # backtrace=True, # 可选：是否记录完整的异常堆栈信息 (即使异常被捕获)
    # diagnose=True,  # 可选：是否在异常时记录更详细的诊断信息
)

# 导出一个可以直接使用的 logger 实例
logger = loguru_logger

# --- 使用示例 (可以在其他模块中这样导入和使用) ---
# from .logger import logger # 或者 from project_root.src.logger import logger (取决于启动方式)
#
# logger.debug("这是一条调试信息，仅输出到文件 (如果文件级别足够低)。")
# logger.info("这是一条普通信息。")
# logger.warning("这是一条警告信息。")
# logger.error("这是一条错误信息。")
# try:
#     1 / 0
# except ZeroDivisionError:
#     logger.exception("捕获到一个异常！") # exception 会自动记录堆栈信息

if __name__ == "__main__":
    # 用于测试 logger.py 本身的配置
    logger.info(
        f"Adapter 日志模块测试。控制台级别: {CONSOLE_LOG_LEVEL}, 文件级别: {FILE_LOG_LEVEL}"
    )
    logger.info(f"日志文件将保存在: {LOG_DIR.resolve()}")
    logger.debug("这条 debug 信息应该只出现在文件中。")
    logger.info("这条 info 信息应该出现在控制台和文件中。")
    logger.warning("一条警告测试。")
    logger.error("一条错误测试。")
    try:
        x = 1 / 0
    except ZeroDivisionError:
        logger.exception("测试异常记录。")
    logger.success("日志模块测试完成。")  # loguru 支持 success 级别
