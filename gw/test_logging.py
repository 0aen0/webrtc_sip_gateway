# test_logging.py
import logging
from logging_manager import LoggingManager
from config_manager import ConfigManager

def test_direction_logging():
    """Тестирование логирования с направлениями"""
    config = ConfigManager()
    logging_manager = LoggingManager(config)
    
    # Получаем тестовый логгер
    logger = logging_manager.get_direction_aware_logger("test_module")
    
    print("=== ТЕСТИРОВАНИЕ ЛОГИРОВАНИЯ С НАПРАВЛЕНИЯМИ ===")
    
    # Тестируем обычное логирование
    logger.info("Обычное сообщение без направления")
    
    # Тестируем входящие сообщения
    logger.incoming_info("Входящее SIP сообщение")
    logger.incoming_debug("Входящее DEBUG сообщение")
    logger.incoming_warning("Входящее WARNING сообщение")
    logger.incoming_error("Входящее ERROR сообщение")
    
    # Тестируем исходящие сообщения
    logger.outgoing_info("Исходящее SIP сообщение")
    logger.outgoing_debug("Исходящее DEBUG сообщение")
    logger.outgoing_warning("Исходящее WARNING сообщение")
    logger.outgoing_error("Исходящее ERROR сообщение")
    
    print("=== ТЕСТИРОВАНИЕ ЗАВЕРШЕНО ===")

if __name__ == "__main__":
    test_direction_logging()