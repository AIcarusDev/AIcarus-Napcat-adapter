# aicarus_napcat_adapter/src/config.py
# Adapter 项目专属的配置模块，使用 tomlkit，并包含版本管理

import os
import sys  # 用于 sys.exit()
import shutil  # 用于文件复制和移动
import tomlkit
import datetime  # 用于生成备份文件名
from pathlib import Path
from typing import Any, Optional, Dict, Union  # Union 用于 tomlkit 的类型提示

try:
    from .logger import logger
except ImportError:

    class FallbackLogger:
        def info(self, msg: str):
            print(f"INFO (config.py): {msg}")

        def warning(self, msg: str):
            print(f"WARNING (config.py): {msg}")

        def error(self, msg: str):
            print(f"ERROR (config.py): {msg}")

        def critical(self, msg: str):
            print(f"CRITICAL (config.py): {msg}")

        def exception(self, msg: str):
            print(f"EXCEPTION (config.py): {msg}")

    logger = FallbackLogger()  # type: ignore

# --- 路径定义 ---
# 项目根目录 (假设 config.py 在 src/ 下，run_adapter.py 在项目根)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"  # 运行时配置文件目录 (可选，可以直接放根目录)
TEMPLATE_CONFIG_PATH = (
    PROJECT_ROOT / "template" / "config_template.toml"
)  # 模板文件路径
ACTUAL_CONFIG_PATH = PROJECT_ROOT / "config.toml"  # 实际使用的配置文件路径
BACKUP_DIR = PROJECT_ROOT / "config_backups"  # 旧配置文件备份目录

# 确保配置和备份目录存在
# CONFIG_DIR.mkdir(parents=True, exist_ok=True) # 如果配置文件放在 config/ 子目录
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


# --- 配置数据类 ---
class AdapterConfigData:
    config_version: str = "0.0.0"  # 用于存储从实际配置文件中读取的版本号
    adapter_server_host: str = "0.0.0.0"
    adapter_server_port: int = 8095
    core_connection_url: str = "ws://127.0.0.1:8000/ws"
    core_platform_id: str = "napcat_adapter_default_instance"
    bot_nickname: str = ""
    force_self_id: str = ""  # 新增: 强制指定的机器人QQ号
    napcat_heartbeat_interval_seconds: int = 30

    def __init__(
        self, data: Union[Dict[str, Any], tomlkit.TOMLDocument]
    ):  # 接受字典或TOMLDocument
        # 从 data 中读取配置，如果键不存在，则使用类属性中定义的默认值
        self.config_version = str(data.get("config_version", self.config_version))

        adapter_server_settings = data.get("adapter_server", {})
        self.adapter_server_host = str(
            adapter_server_settings.get("host", self.adapter_server_host)
        )
        self.adapter_server_port = int(
            adapter_server_settings.get("port", self.adapter_server_port)
        )

        core_connection_settings = data.get("core_connection", {})
        self.core_connection_url = str(
            core_connection_settings.get("url", self.core_connection_url)
        )
        self.core_platform_id = str(
            core_connection_settings.get("platform_id", self.core_platform_id)
        )

        bot_settings_data = data.get("bot_settings", {})
        self.bot_nickname = str(bot_settings_data.get("nickname", self.bot_nickname))
        self.force_self_id = str(
            bot_settings_data.get("force_self_id", self.force_self_id)
        )  # 读取 force_self_id
        self.napcat_heartbeat_interval_seconds = int(
            bot_settings_data.get(
                "napcat_heartbeat_interval_seconds",
                self.napcat_heartbeat_interval_seconds,
            )
        )

        # 示例：如果未来模板增加了新的配置段或键，可以在这里安全地获取
        # new_section = data.get("another_section", {})
        # self.new_setting = str(new_section.get("new_setting", "default_value_if_not_in_class"))


_global_config_instance: Optional[AdapterConfigData] = None


def _merge_toml_data(
    new_data: tomlkit.TOMLDocument, old_data: tomlkit.TOMLDocument
) -> tomlkit.TOMLDocument:
    """
    将旧配置 (old_data) 中的值合并到新配置模板 (new_data) 中。
    new_data 作为基础结构，old_data 中的同名键值会覆盖 new_data 中的值，
    除非该键在 new_data 中不存在（表示模板中已移除该项）。
    特别处理 config_version，始终使用 new_data (模板) 的版本。
    """
    logger.info("正在尝试合并旧的配置值到新的配置模板...")

    # 遍历旧配置的顶层键
    for key in old_data:
        if key == "config_version":  # 版本号始终以新模板为准
            logger.debug(f"  版本号将使用新模板的值: {new_data.get(key)}")
            continue

        if key in new_data:
            old_item = old_data[key]
            new_item = new_data[key]

            # 如果两者都是表 (table)，则递归合并
            if isinstance(old_item, tomlkit.items.Table) and isinstance(
                new_item, tomlkit.items.Table
            ):
                logger.debug(f"  递归合并配置段: [{key}]")
                # 注意：tomlkit 的 Table 不是直接的 dict，需要转换为 dict 再递归，或实现 Table 的递归合并
                # 为了简单起见，这里只做一层覆盖，如果深层结构变化复杂，可能需要更精细的合并逻辑
                # 或者，更简单的方式是，如果旧配置中存在，就用旧的整个表覆盖新的（如果表结构没大变）
                # 这里我们采用更保守的策略：如果新模板中有这个表，就用旧表中的同名键去覆盖新表中的键
                for sub_key in old_item:
                    if sub_key in new_item:
                        if isinstance(
                            old_item[sub_key], type(new_item[sub_key])
                        ):  # 类型相同才覆盖
                            new_item[sub_key] = old_item[sub_key]
                            logger.debug(
                                f"    合并值: [{key}].{sub_key} = {old_item[sub_key]}"
                            )
                        else:
                            logger.warning(
                                f"    跳过合并: [{key}].{sub_key} 类型不匹配 (旧: {type(old_item[sub_key])}, 新: {type(new_item[sub_key])})。保留模板值。"
                            )
                    else:
                        logger.info(
                            f"    旧配置项 [{key}].{sub_key} 在新模板中不存在，已忽略。"
                        )
            # 如果不是表，且类型相同，则用旧值覆盖 (简单值或数组)
            elif isinstance(old_item, type(new_item)):
                new_data[key] = old_item
                logger.debug(f"  合并值: {key} = {old_item}")
            else:
                # 类型不同，保留新模板的值和结构
                logger.warning(
                    f"  跳过合并: 键 '{key}' 类型不匹配 (旧: {type(old_item)}, 新: {type(new_item)})。保留模板值。"
                )
        else:
            # 旧配置中的键在新模板中不存在，说明该配置项可能已被废弃
            logger.info(f"  旧配置项 '{key}' 在新模板中不存在，已忽略。")

    return new_data


def _handle_config_file_and_version() -> bool:
    """
    处理配置文件的存在性、版本检查和更新。
    返回 True 如果配置文件被创建或更新，提示用户检查并退出。
    返回 False 如果配置文件无需更改，程序可以继续。
    """
    if not TEMPLATE_CONFIG_PATH.exists():
        logger.critical(
            f"错误：配置文件模板 {TEMPLATE_CONFIG_PATH} 未找到！程序无法继续。"
        )
        sys.exit(1)  # 模板不存在是致命错误

    template_doc = tomlkit.parse(TEMPLATE_CONFIG_PATH.read_text(encoding="utf-8"))
    expected_version = template_doc.get("config_version")
    if not expected_version:
        logger.critical(
            f"错误：配置文件模板 {TEMPLATE_CONFIG_PATH} 中缺少 'config_version' 字段！"
        )
        sys.exit(1)
    expected_version = str(expected_version)

    config_action_message = ""  # 用于最后提示用户的消息

    if not ACTUAL_CONFIG_PATH.exists():
        logger.warning(f"配置文件 {ACTUAL_CONFIG_PATH} 不存在，将从模板创建。")
        try:
            shutil.copy2(TEMPLATE_CONFIG_PATH, ACTUAL_CONFIG_PATH)
            config_action_message = f"已从模板创建新的配置文件: {ACTUAL_CONFIG_PATH}"
            logger.info(config_action_message)
            return True  # 新创建，需要用户检查
        except Exception as e:
            logger.critical(f"从模板复制配置文件失败: {e}", exc_info=True)
            sys.exit(1)  # 复制失败是致命错误

    # 实际配置文件存在，进行版本检查
    try:
        actual_doc_str = ACTUAL_CONFIG_PATH.read_text(encoding="utf-8")
        actual_doc = tomlkit.parse(actual_doc_str)
    except Exception as e:
        logger.error(f"解析现有配置文件 {ACTUAL_CONFIG_PATH} 失败: {e}", exc_info=True)
        backup_path = (
            BACKUP_DIR
            / f"{ACTUAL_CONFIG_PATH.name}_corrupted_{Path.cwd().name}_{os.getpid()}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.toml"
        )
        try:
            shutil.move(
                str(ACTUAL_CONFIG_PATH), str(backup_path)
            )  # shutil.move 需要字符串路径
            logger.info(f"已备份损坏的配置文件到: {backup_path}")
        except Exception as e_backup:
            logger.error(f"备份损坏的配置文件失败: {e_backup}")

        logger.warning("将从模板重新创建配置文件。")
        shutil.copy2(TEMPLATE_CONFIG_PATH, ACTUAL_CONFIG_PATH)
        config_action_message = (
            f"现有配置文件 {ACTUAL_CONFIG_PATH} 损坏，已从模板重新创建。"
        )
        logger.info(config_action_message)
        return True  # 重新创建，需要用户检查

    actual_version = actual_doc.get("config_version")
    if actual_version:
        actual_version = str(actual_version)

    if actual_version == expected_version:
        logger.info(
            f"配置文件版本 ({actual_version}) 与模板版本 ({expected_version}) 一致，无需更新。"
        )
        return False  # 版本一致，程序继续

    # 版本不一致，需要更新
    logger.warning(
        f"配置文件版本 ({actual_version or '未找到'}) 与模板版本 ({expected_version}) 不一致，将进行更新。"
    )

    backup_filename = f"{ACTUAL_CONFIG_PATH.name}_backup_v{actual_version or 'unknown'}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.toml"
    backup_path = BACKUP_DIR / backup_filename
    try:
        shutil.copy2(ACTUAL_CONFIG_PATH, backup_path)  # 备份旧的
        logger.info(
            f"已备份旧的配置文件 (版本: {actual_version or '未知'}) 到: {backup_path}"
        )
    except Exception as e_backup:
        logger.error(
            f"备份旧的配置文件失败: {e_backup}。更新将基于内存中的旧配置（如果可用）。"
        )
        # 即使备份失败，我们仍然尝试基于内存中的 actual_doc 进行合并

    # 以新模板为基础，合并旧配置的值
    updated_doc = _merge_toml_data(
        template_doc.copy(), actual_doc
    )  # 使用模板的副本进行合并

    try:
        ACTUAL_CONFIG_PATH.write_text(tomlkit.dumps(updated_doc), encoding="utf-8")
        config_action_message = (
            f"配置文件已从版本 {actual_version or '未知'} 更新到版本 {expected_version}。\n"
            f"旧的配置文件已备份到: {backup_path if 'backup_path' in locals() and backup_path.exists() else '备份失败'}"
        )
        logger.info(config_action_message.replace("\n", " "))
        return True  # 更新完成，需要用户检查
    except Exception as e_write:
        logger.critical(
            f"写入更新后的配置文件 {ACTUAL_CONFIG_PATH} 失败: {e_write}", exc_info=True
        )
        logger.critical(
            "程序将使用更新前的配置（如果已加载），或者可能无法正确运行。请检查文件权限和磁盘空间。"
        )
        # 此时，ACTUAL_CONFIG_PATH 可能仍是旧版本或损坏，取决于写入失败的程度
        # 为了安全，可以考虑让程序退出
        sys.exit(1)


def load_and_get_config() -> AdapterConfigData:
    global _global_config_instance
    if _global_config_instance is not None:
        return _global_config_instance

    # --- 版本检查和文件处理 ---
    # 这个函数现在会处理文件创建、版本比较、合并，并在需要时退出
    should_exit_after_config_action = _handle_config_file_and_version()

    if should_exit_after_config_action:
        logger.info(
            "--------------------------------------------------------------------"
        )
        logger.info("重要提示: Adapter 的配置文件已被创建或更新。")
        logger.info(f"请检查位于 '{ACTUAL_CONFIG_PATH.resolve()}' 的配置文件内容,")
        logger.info("特别是新添加或已更改的配置项，确保它们符合您的需求。")
        logger.info("完成检查和必要的修改后，请重新启动 Adapter。")
        logger.info(
            "--------------------------------------------------------------------"
        )
        sys.exit(0)  # 终止程序，让用户检查配置

    # --- 如果程序没有退出，说明配置文件存在且版本正确，可以加载 ---
    try:
        config_string = ACTUAL_CONFIG_PATH.read_text(encoding="utf-8")
        config_data_dict = tomlkit.parse(config_string)

        _global_config_instance = AdapterConfigData(config_data_dict)

        logger.info(f"Adapter 配置已从 {ACTUAL_CONFIG_PATH} 加载。")
        logger.info(f"  - 配置版本: {_global_config_instance.config_version}")
        logger.info(
            f"  - Adapter Server (监听 Napcat): ws://{_global_config_instance.adapter_server_host}:{_global_config_instance.adapter_server_port}"
        )
        logger.info(
            f"  - Core Connection URL: {_global_config_instance.core_connection_url}"
        )
        logger.info(f"  - Core Platform ID: {_global_config_instance.core_platform_id}")
        if _global_config_instance.bot_nickname:
            logger.info(f"  - Bot Nickname: '{_global_config_instance.bot_nickname}'")
        else:
            logger.info("  - Bot Nickname: 未设置")
        if _global_config_instance.force_self_id:  # 新增日志
            logger.info(
                f"  - Forced Bot Self ID: '{_global_config_instance.force_self_id}'"
            )
        else:
            logger.info("  - Forced Bot Self ID: 未设置 (将自动获取)")

        return _global_config_instance
    except tomlkit.exceptions.TOMLKitError as e:
        logger.critical(
            f"解析 Adapter 配置文件 {ACTUAL_CONFIG_PATH} 失败: {e}", exc_info=True
        )
        raise SystemExit(f"配置文件错误，程序无法启动: {e}") from e
    except Exception as e:
        logger.critical(f"加载 Adapter 配置时发生未知错误: {e}", exc_info=True)
        raise SystemExit(f"配置加载错误，程序无法启动: {e}") from e


def get_config() -> AdapterConfigData:
    if _global_config_instance is None:
        return load_and_get_config()
    return _global_config_instance


global_config: AdapterConfigData = get_config()

if __name__ == "__main__":
    logger.info("--- Adapter config.py 模块独立测试 ---")
    try:
        # 测试前，确保 template/config_template.toml 存在
        # 可以手动删除项目根目录的 config.toml 来完整测试创建/更新流程
        # if ACTUAL_CONFIG_PATH.exists():
        #     ACTUAL_CONFIG_PATH.unlink(missing_ok=True)
        #     logger.info(f"已删除 {ACTUAL_CONFIG_PATH} 以进行创建/更新测试。")

        cfg_instance = get_config()  # 这会触发版本检查和可能的退出

        # 如果程序没有因为版本更新而退出，才会执行到这里
        logger.info("配置加载测试成功 (程序未因版本更新而退出)。")
        logger.info(
            f"Adapter监听地址: {cfg_instance.adapter_server_host}:{cfg_instance.adapter_server_port}"
        )
        logger.info(f"Core WebSocket URL: {cfg_instance.core_connection_url}")
        logger.info(f"Core Platform ID: {cfg_instance.core_platform_id}")
        if cfg_instance.bot_nickname:
            logger.info(f"Bot 昵称: '{cfg_instance.bot_nickname}'")
        else:
            logger.info("Bot 昵称: 未设置")
        if cfg_instance.force_self_id:  # 新增测试日志
            logger.info(f"强制 Bot ID: '{cfg_instance.force_self_id}'")
        else:
            logger.info("强制 Bot ID: 未设置")
        logger.info(
            f"Napcat 心跳间隔: {cfg_instance.napcat_heartbeat_interval_seconds} 秒"
        )
        logger.info(
            f"通过 global_config 访问 Core URL: {global_config.core_connection_url}"
        )

    except FileNotFoundError as e_fnf:
        logger.error(f"测试失败：配置文件操作问题 - {e_fnf}")
    except SystemExit as e_sys_exit:
        logger.info(
            f"测试因 SystemExit 中断 (这可能是预期的，因为配置被创建或更新了): {e_sys_exit.code}"
        )
    except Exception:
        logger.exception("config.py 模块测试时发生意外错误:")
    logger.info("--- Adapter config.py 模块测试结束 ---")
