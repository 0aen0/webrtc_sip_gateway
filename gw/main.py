import asyncio
import signal
import sys

from websocket_bridge import WebSocketBridge
from sip_client import SIPClient
from simple_audio_handler import SimpleAudioHandler
from rest_api import RESTAPI
from config_manager import ConfigManager
from logging_manager import LoggingManager

class SIPGateway:
    def __init__(self):
        self.config = ConfigManager()
        self.logging_manager = LoggingManager(self.config)
        self.logger = self.logging_manager.get_logger("sip_gateway")
        
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
        
        # Взаимные ссылки
        self.websocket_bridge.set_sip_client(self.sip_client)
        self.sip_client.set_websocket_bridge(self.websocket_bridge)
        self.rest_api.set_sip_gateway(self)
        
        # Setup audio callback
        self.audio_handler.set_send_audio_callback(self._handle_outgoing_audio)
        
    async def _handle_outgoing_audio(self, audio_data):
        """Handle outgoing audio data (to be sent via SIP)"""
        # В реальной реализации здесь будет код для отправки аудио через RTP/SIP
        # Пока просто логируем
        if audio_data and len(audio_data) > 0:
            self.logger.debug(f"Аудио данные для отправки: {len(audio_data)} байт")
        
    async def _handle_incoming_audio(self, audio_data):
        """Handle incoming audio data (received via SIP)"""
        # Воспроизведение входящего аудио
        await self.audio_handler.write_audio(audio_data)
        
    async def start(self):
        """Запуск всех компонентов"""
        self.logger.info("Запуск SIP шлюза...")
        
        try:
            # Запуск WebSocket сервера
            if not await self.websocket_bridge.start_server():
                raise Exception("Не удалось запустить WebSocket сервер")
            
            # Запуск REST API сервера
            api_task = asyncio.create_task(self.rest_api.start())
            
            # Запуск аудио обработчика (только выход)
            if not await self.audio_handler.start_audio_streams():
                self.logger.warning("Не удалось запустить аудио выходной поток")
            
            self.logger.info("SIP шлюз успешно запущен")
            
            # Авторегистрация если есть настройки
            sip_settings = self.config.get("sip_settings")
            if (sip_settings and sip_settings.get("sip_server") and 
                sip_settings.get("login") and sip_settings.get("password")):
                
                self.logger.info("Автоматическая регистрация на SIP сервере...")
                await self.sip_client.register(**sip_settings)
            
            # Запуск аудио входа по требованию (когда есть активный звонок)
            asyncio.create_task(self._audio_input_manager())
            
            # Ожидание завершения задач
            await api_task
            
        except Exception as e:
            self.logger.error(f"Ошибка запуска шлюза: {e}")
            await self.stop()
            
    async def _audio_input_manager(self):
        """Управление аудио входом в зависимости от состояния звонка"""
        while True:
            try:
                if self.sip_client.is_in_call and not self.audio_handler.input_stream:
                    # Если есть активный звонок, запускаем входной поток
                    await self.audio_handler.start_input_stream()
                    
                    # Запускаем чтение аудио
                    asyncio.create_task(self._audio_reading_loop())
                    
                elif not self.sip_client.is_in_call and self.audio_handler.input_stream:
                    # Если звонка нет, останавливаем входной поток
                    # (останавливается автоматически при stop_audio_streams)
                    pass
                    
                await asyncio.sleep(1)
                
            except Exception as e:
                self.logger.error(f"Ошибка в audio input manager: {e}")
                await asyncio.sleep(5)
    
    async def _audio_reading_loop(self):
        """Цикл чтения аудио когда есть активный звонок"""
        while self.sip_client.is_in_call and self.audio_handler.is_running:
            try:
                await self.audio_handler.read_audio()
                await asyncio.sleep(0.01)  # Small delay to prevent high CPU
            except Exception as e:
                self.logger.error(f"Ошибка в audio reading loop: {e}")
                break
            
    async def stop(self):
        """Остановка всех компонентов"""
        self.logger.info("Остановка SIP шлюза...")
        
        try:
            await self.websocket_bridge.stop_server()
            await self.rest_api.stop()
            await self.sip_client.disconnect()
            await self.audio_handler.stop_audio_streams()
            
        except Exception as e:
            self.logger.error(f"Ошибка при остановке: {e}")
        finally:
            self.logger.info("SIP шлюз остановлен")
            self.logging_manager.cleanup()
    
    def get_status(self) -> dict:
        """Получить статус шлюза"""
        return {
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

async def main():
    gateway = SIPGateway()
    
    # Обработка сигналов завершения
    def signal_handler(signum, frame):
        print("\nПолучен сигнал завершения...")
        asyncio.create_task(gateway.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await gateway.start()
    except KeyboardInterrupt:
        await gateway.stop()
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        await gateway.stop()

if __name__ == "__main__":
    asyncio.run(main())