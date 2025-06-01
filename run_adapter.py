import sys

from src.main_aicarus import main_aicarus_entry
from src.logger import logger  # 现在可以尝试导入 Adapter 自己的 logger

if __name__ == "__main__":
    logger.info("AIcarus Napcat Adapter 正在通过 run_adapter.py 启动...")
    try:
        main_aicarus_entry()
    except Exception:
        logger.exception("AIcarus Napcat Adapter 运行时发生严重错误:")
        sys.exit(1)
    finally:
        logger.info("AIcarus Napcat Adapter 执行完毕。")
