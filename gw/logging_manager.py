import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import os
import sys
from typing import Dict
import json
import time

class DirectionFilter(logging.Filter):
    """Фильтр для добавления направления сообщения"""
    def __init__(self):
        super().__init__()
        self.direction = " "  # По умолчанию без направления
        
    def filter(self, record):
        if not hasattr(record, 'direction'):
            record.direction = self.direction
        return True


class SafeFormatter(logging.Formatter):
    """Formatter that guarantees a 'direction' attribute exists on the record
    to avoid KeyError during percent-style formatting when direction is missing.
    """
    def format(self, record):
        if not hasattr(record, 'direction'):
            # default to a single space so formatting remains aligned
            record.direction = ' '
        return super().format(record)

def get_direction_logger(name: str):
    """Создает логгер с поддержкой направления сообщений"""
    logger = logging.getLogger(name)
    direction_filter = DirectionFilter()
    logger.addFilter(direction_filter)
    
    # Добавляем методы для входящих и исходящих сообщений
    def log_with_direction(self, level, msg, direction, *args, **kwargs):
        original_direction = direction_filter.direction
        direction_filter.direction = direction
        self.log(level, msg, *args, **kwargs)
        direction_filter.direction = original_direction

    # Info level methods
    logger.incoming_info = lambda msg, *args, **kwargs: log_with_direction(logger, logging.INFO, msg, "< ", *args, **kwargs)
    logger.outgoing_info = lambda msg, *args, **kwargs: log_with_direction(logger, logging.INFO, msg, "> ", *args, **kwargs)

    # Debug level methods
    logger.incoming_debug = lambda msg, *args, **kwargs: log_with_direction(logger, logging.DEBUG, msg, "< ", *args, **kwargs)
    logger.outgoing_debug = lambda msg, *args, **kwargs: log_with_direction(logger, logging.DEBUG, msg, "> ", *args, **kwargs)

    # Warning level methods
    logger.incoming_warning = lambda msg, *args, **kwargs: log_with_direction(logger, logging.WARNING, msg, "< ", *args, **kwargs)
    logger.outgoing_warning = lambda msg, *args, **kwargs: log_with_direction(logger, logging.WARNING, msg, "> ", *args, **kwargs)

    # Error level methods
    logger.incoming_error = lambda msg, *args, **kwargs: log_with_direction(logger, logging.ERROR, msg, "< ", *args, **kwargs)
    logger.outgoing_error = lambda msg, *args, **kwargs: log_with_direction(logger, logging.ERROR, msg, "> ", *args, **kwargs)

    # Backward compatibility
    logger.incoming = logger.incoming_info
    logger.outgoing = logger.outgoing_info
    
    return logger

def get_protocol_logger(protocol: str, name: str) -> logging.Logger:
    """Получить логгер для протокола с автоматическим определением направления"""
    full_name = f"{protocol}.{name}" if protocol else name
    logger = get_direction_logger(full_name)
    
    # Добавляем методы для протоколов
    def log_protocol_message(self, direction: str, message: str, level=logging.INFO, *args, **kwargs):
        """Логирование сообщения протокола с направлением"""
        # Находим DirectionFilter в фильтрах логгера
        direction_filter = None
        for filt in self.filters:
            if isinstance(filt, DirectionFilter):
                direction_filter = filt
                break
        
        if direction_filter:
            original_direction = direction_filter.direction
            direction_filter.direction = direction
            self.log(level, message, *args, **kwargs)
            direction_filter.direction = original_direction
        else:
            self.log(level, f"{direction}{message}", *args, **kwargs)
    
    # Добавляем методы для входящих/исходящих сообщений протоколов
    logger.log_received = lambda msg, *args, **kwargs: log_protocol_message(logger, "< ", msg, *args, **kwargs)
    logger.log_sent = lambda msg, *args, **kwargs: log_protocol_message(logger, "> ", msg, *args, **kwargs)
    
    # Специфичные методы для разных протоколов
    if protocol == "sip":
        logger.log_sip_request = lambda method, details="": logger.log_sent(f"SIP запрос {method}" + (f" - {details}" if details else ""))
        logger.log_sip_response = lambda code, text, details="": logger.log_received(f"SIP ответ {code} {text}" + (f" - {details}" if details else ""))
    
    elif protocol == "websocket":
        logger.log_ws_message = lambda direction, msg_type, client="": (
            logger.log_received(f"WebSocket сообщение {msg_type}" + (f" от {client}" if client else "")) 
            if direction == "received" else 
            logger.log_sent(f"WebSocket сообщение {msg_type}" + (f" для {client}" if client else ""))
        )
    
    elif protocol == "rest":
        logger.log_http_request = lambda method, path, client="": logger.log_received(f"HTTP {method} {path}" + (f" от {client}" if client else ""))
        logger.log_http_response = lambda method, path, code, duration=0: logger.log_sent(f"HTTP {method} {path} - {code}" + (f" ({duration:.2f}s)" if duration > 0 else ""))
    
    return logger

class LoggingManager:
    def __init__(self, config_manager):
        self.config = config_manager
        self.logger = None
        self.handlers: Dict[str, logging.Handler] = {}
        self.setup_logging()

    def setup_logging(self):
        """Настройка логирования с поддержкой модульного логирования"""
        logging_config = self.config.get("logging", {})
        
        # ДИАГНОСТИКА: выведем текущую конфигурацию
        print(f"DEBUG: Конфигурация логирования: {json.dumps(logging_config, indent=2)}")
        
        # Настройка логирования по умолчанию
        default_config = logging_config.get("default", {
            "level": "INFO",
            "file": "logs/gateway.log",
            "format": "[{asctime}] [{levelname}] [{name}] {direction}{message}",
            "rotation": "1 day",
            "retention": "30 days"
        })
        
        # ДИАГНОСТИКА: проверим формат
        print(f"DEBUG: Формат по умолчанию: {default_config['format']}")
        
        # Настройка корневого логгера
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, default_config["level"].upper()))
        
        # Очистка существующих обработчиков
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            if hasattr(handler, 'close'):
                handler.close()
        
        # Добавляем фильтр направления к корневому логгеру
        root_direction_filter = DirectionFilter()
        root_logger.addFilter(root_direction_filter)
        print("DEBUG: DirectionFilter добавлен к корневому логгеру")

        # Создаем базовую директорию для логов
        log_dir = os.path.dirname(default_config["file"])
        os.makedirs(log_dir, exist_ok=True)
        print(f"DEBUG: Создана директория для логов: {log_dir}")
        
        # Настройка основного файла логов
        # Преобразуем наш формат в стандартный Python logging format
        format_string = default_config["format"].replace("{asctime}", "%(asctime)s") \
                                               .replace("{levelname}", "%(levelname)s") \
                                               .replace("{name}", "%(name)s") \
                                               .replace("{direction}", "%(direction)s") \
                                               .replace("{message}", "%(message)s")
        
        print(f"DEBUG: Преобразованный формат: {format_string}")
        
        default_formatter = SafeFormatter(format_string, style="%")
        
        # Преобразование параметра rotation в корректный формат
        rotation_mapping = {
            "1 day": "midnight",
            "1 hour": "H",
            "1 minute": "M",
            "1 week": "W0",
            "1 month": "M"
        }
        rotation_value = default_config.get("rotation", "1 day")
        when = rotation_mapping.get(rotation_value, "midnight")
        
        default_handler = TimedRotatingFileHandler(
            default_config["file"],
            when=when,
            interval=1,
            backupCount=int(default_config.get("retention", "30").split()[0])
        )
        default_handler.setFormatter(default_formatter)
        default_handler.setLevel(getattr(logging, default_config["level"].upper()))
        root_logger.addHandler(default_handler)
        self.handlers["default"] = default_handler
        
        print(f"DEBUG: Основной обработчик настроен с форматом: {format_string}")
        
        # Настройка консольного вывода
        console_config = logging_config.get("console", {
            "enabled": True,
            "level": "INFO",
            "format": "[{asctime}] [{levelname}] [{name}] {message}"
        })
        
        if console_config.get("enabled", True):
            console_handler = logging.StreamHandler()
            
            # Преобразуем формат консоли
            console_format_string = console_config.get("format", "[{asctime}] [{levelname}] [{name}] {message}")
            console_format_string = console_format_string.replace("{asctime}", "%(asctime)s") \
                                                       .replace("{levelname}", "%(levelname)s") \
                                                       .replace("{name}", "%(name)s") \
                                                       .replace("{direction}", "%(direction)s") \
                                                       .replace("{message}", "%(message)s")
            
            console_formatter = SafeFormatter(console_format_string, style="%")
            console_handler.setFormatter(console_formatter)
            console_handler.setLevel(getattr(logging, console_config["level"].upper()))
            
            # Настройка кодировки для Windows
            if sys.platform == "win32":
                try:
                    import io
                    console_handler.stream = io.TextIOWrapper(
                        console_handler.stream.buffer, 
                        encoding='utf-8', 
                        errors='replace'
                    )
                except Exception:
                    pass
            
            root_logger.addHandler(console_handler)
            self.handlers["console"] = console_handler
            print(f"DEBUG: Консольный обработчик настроен с форматом: {console_format_string}")
        
        # Создаем логгер для logging_manager в начале
        self.logger = self.get_direction_aware_logger("logging_manager")
        self.logger.setLevel(getattr(logging, default_config["level"].upper()))
        
        # Настройка логгеров модулей
        modules_config = logging_config.get("modules", {})
        for module_name, module_config in modules_config.items():
            if module_config.get("enabled", True):
                self._setup_module_logger(module_name, module_config)
        
        self.logger.outgoing_info(f"Логирование инициализировано с уровнем: {default_config['level']}")
        
        # ДИАГНОСТИКА: проверим настройку
        self._diagnose_logging_setup()

    def _diagnose_logging_setup(self):
        """Диагностика настроек логирования"""
        print("=== ДИАГНОСТИКА НАСТРОЙКИ ЛОГИРОВАНИЯ ===")
        
        root_logger = logging.getLogger()
        print(f"Корневой логгер - обработчиков: {len(root_logger.handlers)}")
        
        for i, handler in enumerate(root_logger.handlers):
            print(f"Обработчик {i}: {type(handler).__name__}")
            if hasattr(handler, 'formatter') and handler.formatter:
                print(f"  Формат: {handler.formatter._fmt}")
            if hasattr(handler, 'baseFilename'):
                print(f"  Файл: {handler.baseFilename}")
        
        # Проверим несколько тестовых логгеров
        test_loggers = ["sip_client", "websocket_bridge", "rest_api", "logging_manager"]
        for logger_name in test_loggers:
            logger = logging.getLogger(logger_name)
            print(f"Логгер '{logger_name}':")
            print(f"  Уровень: {logging.getLevelName(logger.level)}")
            print(f"  Обработчиков: {len(logger.handlers)}")
            print(f"  Фильтров: {len(logger.filters)}")
            for filt in logger.filters:
                print(f"    Фильтр: {type(filt).__name__}")
        
        print("=== КОНЕЦ ДИАГНОСТИКИ ===")

    def _setup_module_logger(self, module_name: str, config: dict):
        """Настройка логгера для отдельного модуля"""
        try:
            logger = self.get_direction_aware_logger(module_name)
            logger.propagate = False  # Отключаем передачу логов родительскому логгеру
            
            # Создаем директорию для логов модуля
            log_file = config.get("file")
            if log_file:
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
                
                # Создаем форматтер с поддержкой direction
                format_string = config.get("format", "[{asctime}] [{levelname}] {direction}{message}")
                format_string = format_string.replace("{asctime}", "%(asctime)s") \
                                           .replace("{levelname}", "%(levelname)s") \
                                           .replace("{name}", "%(name)s") \
                                           .replace("{direction}", "%(direction)s") \
                                           .replace("{message}", "%(message)s")
                
                formatter = SafeFormatter(format_string, style="%")
                
                # Преобразование параметра rotation в корректный формат
                rotation_mapping = {
                    "1 day": "midnight",
                    "1 hour": "H",
                    "1 minute": "M",
                    "1 week": "W0",
                    "1 month": "M"
                }
                rotation_value = config.get("rotation", "1 day")
                when = rotation_mapping.get(rotation_value, "midnight")
                
                # Создаем обработчик с ротацией
                handler = TimedRotatingFileHandler(
                    log_file,
                    when=when,
                    interval=1,
                    backupCount=int(config.get("retention", "30").split()[0])
                )
                handler.setFormatter(formatter)
                handler.setLevel(getattr(logging, config.get("level", "INFO").upper()))
                
                # Добавляем обработчик к логгеру
                logger.addHandler(handler)
                self.handlers[f"module_{module_name}"] = handler
                
            logger.setLevel(getattr(logging, config.get("level", "INFO").upper()))
            self.logger.outgoing_debug(f"Настроен логгер для модуля {module_name}")
            
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка настройки логгера для модуля {module_name}: {e}")

    def update_log_level(self, module_name: str, new_level: str) -> bool:
        """Обновление уровня логирования для указанного модуля"""
        try:
            logger = logging.getLogger(module_name)
            logger.setLevel(getattr(logging, new_level.upper()))
            
            # Обновляем конфигурацию
            logging_config = self.config.get("logging", {})
            if "modules" in logging_config and module_name in logging_config["modules"]:
                logging_config["modules"][module_name]["level"] = new_level
                self.config.set("logging", logging_config)
            
            self.logger.outgoing_info(f"Уровень логирования для {module_name} изменен на: {new_level}")
            return True
            
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка изменения уровня логирования для {module_name}: {e}")
            return False

    def get_module_log_file(self, module_name: str) -> str:
        """Получить путь к файлу логов модуля"""
        logging_config = self.config.get("logging", {})
        if "modules" in logging_config and module_name in logging_config["modules"]:
            return logging_config["modules"][module_name].get("file", "")
        return ""

    def get_module_log_level(self, module_name: str) -> str:
        """Получить текущий уровень логирования модуля"""
        logging_config = self.config.get("logging", {})
        if "modules" in logging_config and module_name in logging_config["modules"]:
            return logging_config["modules"][module_name].get("level", "INFO")
        return "INFO"

    def get_logger(self, name: str) -> logging.Logger:
        """Получить логгер для указанного компонента"""
        return get_direction_logger(name)

    def get_direction_aware_logger(self, name: str) -> logging.Logger:
        """Получить логгер с полной поддержкой направления"""
        logger = logging.getLogger(name)
        
        # Убедимся, что у логгера есть DirectionFilter
        has_direction_filter = any(isinstance(filt, DirectionFilter) for filt in logger.filters)
        if not has_direction_filter:
            direction_filter = DirectionFilter()
            logger.addFilter(direction_filter)
        
        # Добавляем методы для входящих и исходящих сообщений
        def add_direction_methods(logger_obj):
            direction_filter = None
            for filt in logger_obj.filters:
                if isinstance(filt, DirectionFilter):
                    direction_filter = filt
                    break
            
            if direction_filter:
                def log_with_direction(level, msg, direction, *args, **kwargs):
                    original_direction = direction_filter.direction
                    direction_filter.direction = direction
                    logger_obj.log(level, msg, *args, **kwargs)
                    direction_filter.direction = original_direction

                # Info level methods
                logger_obj.incoming_info = lambda msg, *args, **kwargs: log_with_direction(logging.INFO, msg, "< ", *args, **kwargs)
                logger_obj.outgoing_info = lambda msg, *args, **kwargs: log_with_direction(logging.INFO, msg, "> ", *args, **kwargs)

                # Debug level methods
                logger_obj.incoming_debug = lambda msg, *args, **kwargs: log_with_direction(logging.DEBUG, msg, "< ", *args, **kwargs)
                logger_obj.outgoing_debug = lambda msg, *args, **kwargs: log_with_direction(logging.DEBUG, msg, "> ", *args, **kwargs)

                # Warning level methods
                logger_obj.incoming_warning = lambda msg, *args, **kwargs: log_with_direction(logging.WARNING, msg, "< ", *args, **kwargs)
                logger_obj.outgoing_warning = lambda msg, *args, **kwargs: log_with_direction(logging.WARNING, msg, "> ", *args, **kwargs)

                # Error level methods
                logger_obj.incoming_error = lambda msg, *args, **kwargs: log_with_direction(logging.ERROR, msg, "< ", *args, **kwargs)
                logger_obj.outgoing_error = lambda msg, *args, **kwargs: log_with_direction(logging.ERROR, msg, "> ", *args, **kwargs)

                # Backward compatibility
                logger_obj.incoming = logger_obj.incoming_info
                logger_obj.outgoing = logger_obj.outgoing_info
        
        add_direction_methods(logger)
        return logger

    def get_protocol_logger(self, protocol: str, name: str) -> logging.Logger:
        """Получить логгер для протокола с автоматическим определением направления"""
        return get_protocol_logger(protocol, name)

    def get_enabled_modules(self) -> list:
        """Получить список включенных модулей логирования"""
        logging_config = self.config.get("logging", {})
        modules = logging_config.get("modules", {})
        return [name for name, config in modules.items() if config.get("enabled", True)]

    def cleanup(self):
        """Очистка ресурсов логирования"""
        try:
            # Закрываем все обработчики
            for handler_name, handler in self.handlers.items():
                try:
                    handler.close()
                except Exception as e:
                    print(f"Ошибка закрытия обработчика {handler_name}: {e}")

            # Очищаем обработчики корневого логгера
            root_logger = logging.getLogger()
            for handler in root_logger.handlers[:]:
                handler.close()
                root_logger.removeHandler(handler)
            
            # Очищаем обработчики всех модульных логгеров
            for module_name in self.get_enabled_modules():
                logger = logging.getLogger(module_name)
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)
            
            self.logger.outgoing_info("Ресурсы логирования очищены")
            
        except Exception as e:
            print(f"Ошибка очистки логирования: {e}")
            
    def rotate_logs(self):
        """Принудительная ротация всех лог-файлов"""
        try:
            for handler_name, handler in self.handlers.items():
                if isinstance(handler, (RotatingFileHandler, TimedRotatingFileHandler)):
                    handler.doRollover()
            self.logger.outgoing_info("Выполнена ротация лог-файлов")
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка ротации лог-файлов: {e}")

    def get_log_statistics(self) -> Dict:
        """Получить статистику по логгерам"""
        statistics = {
            "total_loggers": 0,
            "loggers": {},
            "handlers": len(self.handlers)
        }
        
        # Получаем все зарегистрированные логгеры
        manager = logging.getLogger().manager
        if hasattr(manager, 'loggerDict'):
            for logger_name, logger_obj in manager.loggerDict.items():
                if isinstance(logger_obj, logging.Logger):
                    statistics["total_loggers"] += 1
                    statistics["loggers"][logger_name] = {
                        "level": logging.getLevelName(logger_obj.level),
                        "handlers": len(logger_obj.handlers),
                        "filters": len(logger_obj.filters),
                        "disabled": logger_obj.disabled
                    }
        
        return statistics

    def enable_debug_mode(self):
        """Включить режим отладки для всех логгеров"""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Обновляем все обработчики
        for handler in root_logger.handlers:
            handler.setLevel(logging.DEBUG)
        
        # Обновляем модульные логгеры
        for module_name in self.get_enabled_modules():
            logger = logging.getLogger(module_name)
            logger.setLevel(logging.DEBUG)
            for handler in logger.handlers:
                handler.setLevel(logging.DEBUG)
        
        self.logger.outgoing_info("Режим отладки включен для всех логгеров")

    def disable_debug_mode(self):
        """Выключить режим отладки"""
        default_config = self.config.get("logging", {}).get("default", {})
        default_level = getattr(logging, default_config.get("level", "INFO").upper())
        
        root_logger = logging.getLogger()
        root_logger.setLevel(default_level)
        
        # Обновляем все обработчики
        for handler in root_logger.handlers:
            handler.setLevel(default_level)
        
        # Обновляем модульные логгеры согласно конфигурации
        modules_config = self.config.get("logging", {}).get("modules", {})
        for module_name, module_config in modules_config.items():
            if module_config.get("enabled", True):
                logger = logging.getLogger(module_name)
                module_level = getattr(logging, module_config.get("level", "INFO").upper())
                logger.setLevel(module_level)
                for handler in logger.handlers:
                    handler.setLevel(module_level)
        
        self.logger.outgoing_info("Режим отладки выключен, восстановлены настройки из конфигурации")

    def test_direction_logging(self):
        """Тестирование логирования с направлениями"""
        test_logger = self.get_direction_aware_logger("test_direction")
        
        print("=== ТЕСТИРОВАНИЕ ЛОГИРОВАНИЯ С НАПРАВЛЕНИЯМИ ===")
        
        # Тестируем обычное логирование
        test_logger.info("Обычное сообщение без направления")
        
        # Тестируем входящие сообщения
        test_logger.incoming_info("Входящее SIP сообщение")
        test_logger.incoming_debug("Входящее DEBUG сообщение")
        test_logger.incoming_warning("Входящее WARNING сообщение")
        test_logger.incoming_error("Входящее ERROR сообщение")
        
        # Тестируем исходящие сообщения
        test_logger.outgoing_info("Исходящее SIP сообщение")
        test_logger.outgoing_debug("Исходящее DEBUG сообщение")
        test_logger.outgoing_warning("Исходящее WARNING сообщение")
        test_logger.outgoing_error("Исходящее ERROR сообщение")
        
        print("=== ТЕСТИРОВАНИЕ ЗАВЕРШЕНО ===")

    def get_logging_config_summary(self) -> Dict:
        """Получить сводку конфигурации логирования"""
        logging_config = self.config.get("logging", {})
        summary = {
            "default_level": logging_config.get("default", {}).get("level", "INFO"),
            "enabled_modules": [],
            "handlers_count": len(self.handlers),
            "log_files": {}
        }
        
        # Информация о модулях
        modules_config = logging_config.get("modules", {})
        for module_name, module_config in modules_config.items():
            if module_config.get("enabled", True):
                summary["enabled_modules"].append({
                    "name": module_name,
                    "level": module_config.get("level", "INFO"),
                    "file": module_config.get("file", "")
                })
        
        # Информация о файлах логов
        for handler_name, handler in self.handlers.items():
            if hasattr(handler, 'baseFilename'):
                summary["log_files"][handler_name] = handler.baseFilename
        
        return summary