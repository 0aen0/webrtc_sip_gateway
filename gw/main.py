import asyncio
import signal
import sys
import logging
import os
from pathlib import Path

from websocket_bridge import WebSocketBridge
from sip_client import SIPClient
from simple_audio_handler import SimpleAudioHandler
from rest_api import RESTAPI
from config_manager import ConfigManager
from logging_manager import LoggingManager

# Временная диагностика логирования
def check_logging_setup():
    """Проверка настройки логирования"""
    root_logger = logging.getLogger()
    print("=== ДИАГНОСТИКА ЛОГИРОВАНИЯ В MAIN.PY ===")
    print(f"Количество обработчиков корневого логгера: {len(root_logger.handlers)}")
    
    for i, handler in enumerate(root_logger.handlers):
        print(f"Обработчик {i}: {type(handler).__name__}")
        if hasattr(handler, 'formatter') and handler.formatter:
            print(f"  Формат: {handler.formatter._fmt}")
        if hasattr(handler, 'baseFilename'):
            print(f"  Файл: {handler.baseFilename}")
        if hasattr(handler, 'level'):
            print(f"  Уровень: {logging.getLevelName(handler.level)}")
    
    # Проверим несколько ключевых логгеров
    test_loggers = ["sip_gateway", "sip_client", "websocket_bridge", "rest_api", "audio_handler"]
    for logger_name in test_loggers:
        logger = logging.getLogger(logger_name)
        print(f"Логгер '{logger_name}':")
        print(f"  Уровень: {logging.getLevelName(logger.level)}")
        print(f"  Обработчиков: {len(logger.handlers)}")
        print(f"  Фильтров: {len(logger.filters)}")
        for filt in logger.filters:
            print(f"    Фильтр: {type(filt).__name__}")
    
    print("=== КОНЕЦ ДИАГНОСТИКИ ===")

class SIPGateway:
    def __init__(self):
        self.config = ConfigManager()
        self.logging_manager = LoggingManager(self.config)
        
        # Используем direction-aware логгеры
        self.logger = self.logging_manager.get_direction_aware_logger("sip_gateway")
        
        # Инициализация компонентов
        self.websocket_bridge = WebSocketBridge(
            host=self.config.get("websocket_host", "localhost"),
            port=self.config.get("websocket_port", 8765)
        )
        
        self.sip_client = SIPClient()
        self.audio_handler = SimpleAudioHandler()
        self.rest_api = RESTAPI(
            host=self.config.get("rest_host", "localhost"),
            port=self.config.get("rest_port", 8000)
        )

        # Inject direction-aware loggers into components
        try:
            self.sip_client.logger = self.logging_manager.get_direction_aware_logger("sip_client")
            self.logger.outgoing_debug("Логгер sip_client настроен с поддержкой направлений")
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка настройки логгера sip_client: {e}")
        
        try:
            self.websocket_bridge.logger = self.logging_manager.get_direction_aware_logger("websocket_bridge")
            self.logger.outgoing_debug("Логгер websocket_bridge настроен с поддержкой направлений")
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка настройки логгера websocket_bridge: {e}")
        
        try:
            self.audio_handler.logger = self.logging_manager.get_direction_aware_logger("audio_handler")
            self.logger.outgoing_debug("Логгер audio_handler настроен с поддержкой направлений")
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка настройки логгера audio_handler: {e}")
        
        try:
            self.rest_api.logger = self.logging_manager.get_direction_aware_logger("rest_api")
            self.logger.outgoing_debug("Логгер rest_api настроен с поддержкой направлений")
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка настройки логгера rest_api: {e}")
        
        # Взаимные ссылки
        self.websocket_bridge.set_sip_client(self.sip_client)
        self.sip_client.set_websocket_bridge(self.websocket_bridge)
        self.rest_api.set_sip_gateway(self)
        
        # Setup audio callback
        self.audio_handler.set_send_audio_callback(self._handle_outgoing_audio)
        
        self.logger.outgoing_info("SIPGateway инициализирован")
        
    async def _handle_outgoing_audio(self, audio_data):
        """Handle outgoing audio data (to be sent via SIP)"""
        # В реальной реализации здесь будет код для отправки аудио через RTP/SIP
        # Пока просто логируем
        if audio_data and len(audio_data) > 0:
            self.logger.outgoing_debug(f"Аудио данные для отправки: {len(audio_data)} байт")
        
    async def _handle_incoming_audio(self, audio_data):
        """Handle incoming audio data (received via SIP)"""
        # Воспроизведение входящего аудио
        await self.audio_handler.write_audio(audio_data)
        
    async def start(self):
        """Запуск всех компонентов"""
        self.logger.outgoing_info("Запуск SIP шлюза...")
        
        # Тестируем логирование с направлениями перед запуском
        self.logger.outgoing_info("=== ТЕСТИРОВАНИЕ ЛОГИРОВАНИЯ ПЕРЕД ЗАПУСКОМ ===")
        self.logger.incoming_info("Тестовое входящее сообщение")
        self.logger.outgoing_info("Тестовое исходящее сообщение")
        self.logger.incoming_debug("Тестовое входящее DEBUG сообщение")
        self.logger.outgoing_debug("Тестовое исходящее DEBUG сообщение")
        self.logger.incoming_warning("Тестовое входящее WARNING сообщение")
        self.logger.outgoing_warning("Тестовое исходящее WARNING сообщение")
        self.logger.incoming_error("Тестовое входящее ERROR сообщение")
        self.logger.outgoing_error("Тестовое исходящее ERROR сообщение")
        self.logger.outgoing_info("=== ТЕСТИРОВАНИЕ ЗАВЕРШЕНО ===")
        
        try:
            # Запуск WebSocket сервера
            self.logger.outgoing_info("Запуск WebSocket сервера...")
            if not await self.websocket_bridge.start_server():
                self.logger.outgoing_error("Не удалось запустить WebSocket сервер")
                raise Exception("Не удалось запустить WebSocket сервер")
            self.logger.outgoing_info("WebSocket сервер успешно запущен")
            
            # Запуск REST API сервера
            self.logger.outgoing_info("Запуск REST API сервера...")
            api_task = asyncio.create_task(self.rest_api.start())
            self.logger.outgoing_info("REST API сервер запущен в фоновой задаче")
            
            # Запуск аудио обработчика (только выход)
            self.logger.outgoing_info("Запуск аудио обработчика...")
            if not await self.audio_handler.start_audio_streams():
                self.logger.outgoing_warning("Не удалось запустить аудио выходной поток")
            else:
                self.logger.outgoing_info("Аудио обработчик успешно запущен")
            
            self.logger.outgoing_info("SIP шлюз успешно запущен")
            
            # Проверяем настройки автоподключения
            sip_settings = self.config.get("sip_settings", {})
            auto_connect = sip_settings.get("auto_connect", False)
            
            if (auto_connect and sip_settings.get("sip_server") and 
                sip_settings.get("login") and sip_settings.get("password")):
                self.logger.outgoing_info("Автоматическая регистрация на SIP сервере (auto_connect=True)...")
                await self.sip_client.register(**sip_settings)
            else:
                self.logger.outgoing_info("Автоматическая регистрация отключена (auto_connect=False). Ожидание команды от frontend...")
            
            # Запуск аудио входа по требованию (когда есть активный звонок)
            self.logger.outgoing_info("Запуск менеджера аудио входа...")
            asyncio.create_task(self._audio_input_manager())
            self.logger.outgoing_info("Менеджер аудио входа запущен")
            
            # Ожидание завершения задач
            self.logger.outgoing_info("Ожидание завершения задач...")
            await api_task
            
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка запуска шлюза: {e}")
            await self.stop()
            
    async def _audio_input_manager(self):
        """Управление аудио входом в зависимости от состояния звонка"""
        self.logger.outgoing_info("Запущен менеджер аудио входа")
        
        while True:
            try:
                if self.sip_client.is_in_call and not self.audio_handler.input_stream:
                    # Если есть активный звонок, запускаем входной поток
                    self.logger.outgoing_info("Активный звонок обнаружен - запуск входного аудио потока")
                    await self.audio_handler.start_input_stream()
                    
                    # Запускаем чтение аудио
                    self.logger.outgoing_info("Запуск цикла чтения аудио")
                    asyncio.create_task(self._audio_reading_loop())
                    
                elif not self.sip_client.is_in_call and self.audio_handler.input_stream:
                    # Если звонка нет, останавливаем входной поток
                    self.logger.outgoing_info("Звонок завершен - остановка входного аудио потока")
                    # (останавливается автоматически при stop_audio_streams)
                    pass
                    
                await asyncio.sleep(1)
                
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка в audio input manager: {e}")
                await asyncio.sleep(5)
    
    async def _audio_reading_loop(self):
        """Цикл чтения аудио когда есть активный звонок"""
        self.logger.outgoing_info("Запущен цикл чтения аудио")
        
        read_count = 0
        while self.sip_client.is_in_call and self.audio_handler.is_running:
            try:
                await self.audio_handler.read_audio()
                read_count += 1
                if read_count % 100 == 0:  # Логируем каждые 100 чтений
                    self.logger.outgoing_debug(f"Прочитано аудио блоков: {read_count}")
                await asyncio.sleep(0.01)  # Small delay to prevent high CPU
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка в audio reading loop: {e}")
                break
        
        self.logger.outgoing_info(f"Цикл чтения аудио завершен. Всего прочитано блоков: {read_count}")
            
    async def stop(self):
        """Остановка всех компонентов"""
        self.logger.outgoing_info("Остановка SIP шлюза...")
        
        try:
            self.logger.outgoing_info("Остановка WebSocket сервера...")
            await self.websocket_bridge.stop_server()
            self.logger.outgoing_info("WebSocket сервер остановлен")
            
            self.logger.outgoing_info("Остановка REST API сервера...")
            await self.rest_api.stop()
            self.logger.outgoing_info("REST API сервер остановлен")
            
            self.logger.outgoing_info("Отключение от SIP сервера...")
            await self.sip_client.disconnect()
            self.logger.outgoing_info("Отключение от SIP сервера завершено")
            
            self.logger.outgoing_info("Остановка аудио потоков...")
            await self.audio_handler.stop_audio_streams()
            self.logger.outgoing_info("Аудио потоки остановлены")
            
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка при остановке: {e}")
        finally:
            self.logger.outgoing_info("SIP шлюз остановлен")
            self.logging_manager.cleanup()
    
    def get_status(self) -> dict:
        """Получить статус шлюза"""
        self.logger.outgoing_debug("Запрос статуса шлюза")
        
        status = {
            "websocket": {
                "connected_clients": self.websocket_bridge.get_connection_count(),
                "host": self.config.get("websocket_host"),
                "port": self.config.get("websocket_port")
            },
            "sip": self.sip_client.get_status(),
            "audio": {
                "running": self.audio_handler.is_running,
                "has_input": self.audio_handler.input_stream is not None,
                "has_output": self.audio_handler.output_stream is not None
            },
            "rest_api": {
                "host": self.config.get("rest_host"),
                "port": self.config.get("rest_port"),
                "status": "running"
            },
            "logging": {
                "level": self.config.get("log_level", "INFO"),
                "file": self.config.get("log_file")
            }
        }
        
        self.logger.outgoing_debug("Статус шлюза сформирован")
        return status

async def main():
    # Создаем необходимые директории
    os.makedirs("logs", exist_ok=True)
    os.makedirs("browser_client", exist_ok=True)
    
    print("=== ЗАПУСК SIP GATEWAY ===")
    print("Созданы необходимые директории: logs/, browser_client/")
    
    # Проверяем настройку логирования перед созданием gateway
    check_logging_setup()
    
    gateway = SIPGateway()
    
    # Тестируем логирование с направлениями
    print("=== ТЕСТИРУЕМ ЛОГИРОВАНИЕ С НАПРАВЛЕНИЯМИ ===")
    gateway.logger.incoming_info("ТЕСТ: Входящее сообщение при запуске")
    gateway.logger.outgoing_info("ТЕСТ: Исходящее сообщение при запуске")
    print("=== ТЕСТИРОВАНИЕ ЗАВЕРШЕНО ===")
    
    # Обработка сигналов завершения
    def signal_handler(signum, frame):
        print(f"\nПолучен сигнал завершения {signum}...")
        asyncio.create_task(gateway.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        print("Запуск основного цикла SIP Gateway...")
        await gateway.start()
    except KeyboardInterrupt:
        print("Получен сигнал KeyboardInterrupt...")
        await gateway.stop()
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        await gateway.stop()
    finally:
        print("SIP Gateway завершил работу")

if __name__ == "__main__":
    # Проверяем наличие необходимых файлов
    required_files = ["config.json", "requirements.txt"]
    for file in required_files:
        if not os.path.exists(file):
            print(f"ВНИМАНИЕ: Файл {file} не найден!")
    
    # Проверяем настройки конфигурации
    config = ConfigManager()
    sip_settings = config.get("sip_settings", {})
    
    print("=== ПРОВЕРКА КОНФИГУРАЦИИ ===")
    print(f"WebSocket: {config.get('websocket_host')}:{config.get('websocket_port')}")
    print(f"REST API: {config.get('rest_host')}:{config.get('rest_port')}")
    
    if sip_settings.get("sip_server"):
        print(f"SIP сервер: {sip_settings.get('sip_server')}:{sip_settings.get('sip_port', 5060)}")
        print(f"SIP логин: {sip_settings.get('login')}")
        print(f"SIP номер: {sip_settings.get('number')}")
        print(f"Автоподключение: {sip_settings.get('auto_connect', False)}")
    else:
        print("SIP настройки не заданы - требуется ручная регистрация")
    
    print("=== ЗАПУСК ПРИЛОЖЕНИЯ ===")
    
    # Запускаем основную функцию
    asyncio.run(main())