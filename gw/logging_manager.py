import logging
from logging.handlers import RotatingFileHandler
import os
import sys

class LoggingManager:
    def __init__(self, config_manager):
        self.config = config_manager
        self.logger = None
        self.setup_logging()

    def setup_logging(self):
        """Настройка логирования с поддержкой изменения уровня"""
        log_level = self.config.get("log_level", "INFO")
        log_file = self.config.get("log_file", "logs/gateway.log")
        
        # Создаем директорию для логов
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # Форматтер
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Файловый обработчик
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5
        )
        file_handler.setFormatter(formatter)
        
        # Консольный обработчик с поддержкой Unicode
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        
        # Настройка кодировки для консоли Windows
        if sys.platform == "win32":
            try:
                # Пытаемся установить UTF-8 кодировку для консоли
                import io
                console_handler.stream = io.TextIOWrapper(
                    console_handler.stream.buffer, 
                    encoding='utf-8', 
                    errors='replace'
                )
            except Exception:
                # Если не получилось, используем обычный обработчик
                pass
        
        # Настройка корневого логгера
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper()))
        
        # Удаляем старые обработчики
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Добавляем новые обработчики
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        
        # Устанавливаем уровень для всех наших логгеров
        self._setup_component_loggers(log_level)
        
        self.logger = logging.getLogger("logging_manager")
        self.logger.info(f"Логирование инициализировано с уровнем: {log_level}")

    def _setup_component_loggers(self, log_level):
        """Настройка уровней логирования для всех компонентов"""
        components = [
            "sip_gateway",
            "websocket_bridge", 
            "sip_client",
            "rest_api",
            "audio_handler",
            "logging_manager"
        ]
        
        for component in components:
            logger = logging.getLogger(component)
            logger.setLevel(getattr(logging, log_level.upper()))

    def update_log_level(self, new_level):
        """Обновление уровня логирования для всех компонентов"""
        try:
            # Обновляем конфигурацию
            self.config.set("log_level", new_level)
            
            # Устанавливаем новый уровень для корневого логгера
            root_logger = logging.getLogger()
            root_logger.setLevel(getattr(logging, new_level.upper()))
            
            # Обновляем уровни для всех компонентов
            self._setup_component_loggers(new_level)
            
            self.logger.info(f"Уровень логирования изменен на: {new_level}")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка изменения уровня логирования: {e}")
            return False

    def get_log_file_path(self):
        """Получить путь к файлу логов"""
        return self.config.get("log_file", "logs/gateway.log")

    def get_current_log_level(self):
        """Получить текущий уровень логирования"""
        return self.config.get("log_level", "INFO")

    def get_logger(self, name):
        """Получить логгер для указанного компонента"""
        return logging.getLogger(name)

    def cleanup(self):
        """Очистка ресурсов логирования"""
        try:
            root_logger = logging.getLogger()
            for handler in root_logger.handlers[:]:
                handler.close()
                root_logger.removeHandler(handler)
            
            self.logger.info("Ресурсы логирования очищены")
            
        except Exception as e:
            print(f"Ошибка очистки логирования: {e}")