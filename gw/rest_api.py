import asyncio
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn
import os
from pathlib import Path
import json
import time

from config_manager import ConfigManager

class RESTAPI:
    def __init__(self, host: str = "localhost", port: int = 8000):
        self.host = host
        self.port = port
        self.app = FastAPI(
            title="SIP Gateway API",
            description="REST API для управления SIP шлюзом",
            version="1.0.0"
        )
        self.config = ConfigManager()
        self.sip_gateway = None
        self.logger = logging.getLogger("rest_api")
        
        self.setup_middleware()
        self.setup_routes()
        
    def set_sip_gateway(self, sip_gateway):
        """Set reference to main SIP gateway"""
        self.sip_gateway = sip_gateway
        
    def setup_middleware(self):
        """Setup CORS and logging middleware"""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Добавляем middleware для логирования HTTP запросов
        @self.app.middleware("http")
        async def log_requests(request: Request, call_next):
            start_time = time.time()
            client_host = request.client.host if request.client else "unknown"
            
            # Логируем входящий запрос
            self.logger.incoming_info(f"HTTP {request.method} {request.url.path} от {client_host}")
            
            if self.logger.isEnabledFor(logging.DEBUG):
                headers_dict = dict(request.headers)
                # Скрываем чувствительные данные в логах
                if 'authorization' in headers_dict:
                    headers_dict['authorization'] = '***'
                if 'cookie' in headers_dict:
                    headers_dict['cookie'] = '***'
                self.logger.incoming_debug(f"Заголовки: {headers_dict}")
            
            response = await call_next(request)
            process_time = time.time() - start_time
            
            # Логируем исходящий ответ
            self.logger.outgoing_info(f"HTTP {request.method} {request.url.path} - {response.status_code} ({process_time:.2f}s)")
            
            return response
        
    def setup_routes(self):
        """Setup API routes"""
        
        @self.app.get("/")
        async def root():
            self.logger.incoming_info("GET / - корневой запрос")
            response_data = {
                "message": "SIP Gateway REST API",
                "version": "1.0.0",
                "endpoints": {
                    "settings": "/api/settings",
                    "status": "/api/status", 
                    "sip": "/api/sip",
                    "audio": "/api/audio",
                    "logs": "/api/logs",
                    "logging": "/api/logging/level",
                    "phone": "/phone - демо-телефон"
                }
            }
            self.logger.outgoing_info("Отправка корневого ответа")
            return response_data
        
        @self.app.get("/api/status")
        async def get_status():
            """Get gateway status"""
            self.logger.incoming_info("GET /api/status - запрос статуса")
            try:
                status = {
                    "websocket": {
                        "connected_clients": self.sip_gateway.websocket_bridge.get_connection_count() if self.sip_gateway else 0,
                        "host": self.config.get("websocket_host"),
                        "port": self.config.get("websocket_port")
                    },
                    "sip": self.sip_gateway.sip_client.get_status() if self.sip_gateway and self.sip_gateway.sip_client else {},
                    "audio": {
                        "running": self.sip_gateway.audio_handler.is_running if self.sip_gateway else False
                    },
                    "api": {
                        "host": self.host,
                        "port": self.port,
                        "status": "running"
                    }
                }
                self.logger.outgoing_info("Успешное получение статуса")
                return status
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка получения статуса: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/settings")
        async def get_settings():
            """Get current settings"""
            self.logger.incoming_info("GET /api/settings - запрос настроек")
            try:
                settings = {
                    "websocket": {
                        "host": self.config.get("websocket_host"),
                        "port": self.config.get("websocket_port")
                    },
                    "rest_api": {
                        "host": self.config.get("rest_host"),
                        "port": self.config.get("rest_port")
                    },
                    "sip_settings": self.config.get("sip_settings"),
                    "logging": {
                        "level": self.config.get("log_level", "INFO"),
                        "file": self.config.get("log_file")
                    }
                }
                self.logger.outgoing_info("Успешное получение настроек")
                return settings
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка получения настроек: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.put("/api/settings")
        async def update_settings(settings: Dict[str, Any]):
            """Update gateway settings"""
            self.logger.incoming_info("PUT /api/settings - обновление настроек")
            try:
                # Validate required SIP fields if provided
                if "sip_settings" in settings:
                    sip_settings = settings["sip_settings"]
                    required_fields = ["sip_server", "login", "password", "number"]
                    
                    for field in required_fields:
                        if field not in sip_settings or not sip_settings[field]:
                            self.logger.outgoing_error(f"Отсутствует обязательное поле: {field}")
                            raise HTTPException(
                                status_code=400, 
                                detail=f"Обязательное поле отсутствует: {field}"
                            )
                
                # Save settings
                for key, value in settings.items():
                    if isinstance(value, dict):
                        for sub_key, sub_value in value.items():
                            self.config.set(f"{key}.{sub_key}", sub_value)
                    else:
                        self.config.set(key, value)
                
                # Save to file
                if self.config.save_config():
                    self.logger.outgoing_info("Настройки успешно обновлены")
                    
                    # Update logging if log level changed
                    if "logging" in settings and "level" in settings["logging"]:
                        log_level = settings["logging"]["level"]
                        root_logger = logging.getLogger()
                        root_logger.setLevel(getattr(logging, log_level.upper()))
                        
                        # Update gateway logging if available
                        if self.sip_gateway:
                            self.sip_gateway.setup_logging()
                    
                    # Restart SIP registration if SIP settings changed
                    if "sip_settings" in settings and self.sip_gateway:
                        asyncio.create_task(self._restart_sip_registration())
                    
                    return {"message": "Настройки успешно обновлены", "settings": settings}
                else:
                    self.logger.outgoing_error("Ошибка сохранения настроек")
                    raise HTTPException(status_code=500, detail="Ошибка сохранения настроек")
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка обновления настроек: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.put("/api/logging/level")
        async def update_log_level(payload: Dict[str, str]):
            """Update log level"""
            self.logger.incoming_info("PUT /api/logging/level - изменение уровня логирования")
            try:
                log_level = payload.get("level", "INFO").upper()
                valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
                
                if log_level not in valid_levels:
                    self.logger.outgoing_error(f"Недопустимый уровень логирования: {log_level}")
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Недопустимый уровень логирования. Допустимые: {', '.join(valid_levels)}"
                    )
                
                # Update config
                self.config.set("log_level", log_level)
                self.config.save_config()
                
                # Update logging configuration
                root_logger = logging.getLogger()
                root_logger.setLevel(getattr(logging, log_level))
                
                # Update all component loggers
                loggers = [
                    logging.getLogger("sip_gateway"),
                    logging.getLogger("websocket_bridge"), 
                    logging.getLogger("sip_client"),
                    logging.getLogger("rest_api"),
                    logging.getLogger("audio_handler")
                ]
                
                for logger in loggers:
                    logger.setLevel(getattr(logging, log_level))
                
                # Update gateway logging if available
                if self.sip_gateway:
                    self.sip_gateway.setup_logging()
                
                self.logger.outgoing_info(f"Уровень логирования изменен на: {log_level}")
                
                return {"message": f"Уровень логирования изменен на {log_level}", "level": log_level}
                
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка изменения уровня логирования: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/logging/level")
        async def get_log_level():
            """Get current log level"""
            self.logger.incoming_info("GET /api/logging/level - запрос уровня логирования")
            try:
                level = self.config.get("log_level", "INFO")
                self.logger.outgoing_info(f"Текущий уровень логирования: {level}")
                return {"level": level}
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка получения уровня логирования: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/sip/register")
        async def register_sip(background_tasks: BackgroundTasks):
            """Register on SIP server with current settings"""
            self.logger.incoming_info("POST /api/sip/register - регистрация SIP")
            try:
                sip_settings = self.config.get("sip_settings")
                if not all([sip_settings.get("sip_server"), sip_settings.get("login"), 
                           sip_settings.get("password"), sip_settings.get("number")]):
                    self.logger.outgoing_error("Не все SIP настройки заполнены")
                    raise HTTPException(
                        status_code=400, 
                        detail="Не все SIP настройки заполнены"
                    )
                
                if self.sip_gateway and self.sip_gateway.sip_client:
                    background_tasks.add_task(self._register_sip_task)
                    self.logger.outgoing_info("Запущена фоновая регистрация SIP")
                    return {"message": "Запущена регистрация на SIP сервере"}
                else:
                    self.logger.outgoing_error("SIP клиент не доступен")
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка регистрации SIP: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/sip/unregister")
        async def unregister_sip():
            """Unregister from SIP server"""
            self.logger.incoming_info("POST /api/sip/unregister - отмена регистрации SIP")
            try:
                if self.sip_gateway and self.sip_gateway.sip_client:
                    await self.sip_gateway.sip_client.disconnect()
                    self.logger.outgoing_info("Отключение от SIP сервера выполнено")
                    return {"message": "Отключение от SIP сервера выполнено"}
                else:
                    self.logger.outgoing_error("SIP клиент не доступен")
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка отключения SIP: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/sip/status")
        async def get_sip_status():
            """Get SIP client status"""
            self.logger.incoming_info("GET /api/sip/status - запрос статуса SIP")
            try:
                if self.sip_gateway and self.sip_gateway.sip_client:
                    status = self.sip_gateway.sip_client.get_status()
                    self.logger.outgoing_info("Успешное получение статуса SIP")
                    return status
                else:
                    self.logger.outgoing_error("SIP клиент не доступен")
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка получения статуса SIP: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/call/make")
        async def make_call(payload: Dict[str, str]):
            """Make outgoing call"""
            self.logger.incoming_info("POST /api/call/make - совершение вызова")
            try:
                number = payload.get("number")
                if not number:
                    self.logger.outgoing_error("Не указан номер для вызова")
                    raise HTTPException(status_code=400, detail="Не указан номер")
                
                if self.sip_gateway and self.sip_gateway.sip_client:
                    success = await self.sip_gateway.sip_client.make_call(number)
                    if success:
                        self.logger.outgoing_info(f"Вызов номера {number} инициирован")
                        return {"message": f"Вызов номера {number} initiated"}
                    else:
                        self.logger.outgoing_error("Ошибка совершения вызова")
                        raise HTTPException(status_code=500, detail="Ошибка совершения вызова")
                else:
                    self.logger.outgoing_error("SIP клиент не доступен")
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка совершения вызова: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/call/answer")
        async def answer_call():
            """Answer incoming call"""
            self.logger.incoming_info("POST /api/call/answer - ответ на входящий звонок")
            try:
                if self.sip_gateway and self.sip_gateway.sip_client:
                    success = await self.sip_gateway.sip_client.answer_call()
                    if success:
                        self.logger.outgoing_info("Звонок принят")
                        return {"message": "Звонок принят"}
                    else:
                        self.logger.outgoing_error("Ошибка приема звонка")
                        raise HTTPException(status_code=500, detail="Ошибка приема звонка")
                else:
                    self.logger.outgoing_error("SIP клиент не доступен")
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка приема звонка: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/call/hangup")
        async def hangup_call():
            """Hang up current call"""
            self.logger.incoming_info("POST /api/call/hangup - завершение звонка")
            try:
                if self.sip_gateway and self.sip_gateway.sip_client:
                    success = await self.sip_gateway.sip_client.hangup_call()
                    if success:
                        self.logger.outgoing_info("Звонок завершен")
                        return {"message": "Звонок завершен"}
                    else:
                        self.logger.outgoing_error("Ошибка завершения звонка")
                        raise HTTPException(status_code=500, detail="Ошибка завершения звонка")
                else:
                    self.logger.outgoing_error("SIP клиент не доступен")
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка завершения звонка: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/call/dtmf")
        async def send_dtmf(payload: Dict[str, str]):
            """Send DTMF tone"""
            self.logger.incoming_info("POST /api/call/dtmf - отправка DTMF")
            try:
                digit = payload.get("digit")
                if not digit:
                    self.logger.outgoing_error("Не указана цифра DTMF")
                    raise HTTPException(status_code=400, detail="Не указана цифра DTMF")
                
                if self.sip_gateway and self.sip_gateway.sip_client:
                    success = await self.sip_gateway.sip_client.send_dtmf(digit)
                    if success:
                        self.logger.outgoing_info(f"DTMF отправлен: {digit}")
                        return {"message": f"DTMF отправлен: {digit}"}
                    else:
                        self.logger.outgoing_error("Ошибка отправки DTMF")
                        raise HTTPException(status_code=500, detail="Ошибка отправки DTMF")
                else:
                    self.logger.outgoing_error("SIP клиент не доступен")
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка отправки DTMF: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/api/sip/message")
        async def send_sip_message(payload: Dict[str, str]):
            """Send SIP MESSAGE"""
            self.logger.incoming_info("POST /api/sip/message - отправка SIP сообщения")
            try:
                to_number = payload.get("to_number")
                content = payload.get("content")
                
                if not to_number or not content:
                    self.logger.outgoing_error("Не указан номер получателя или содержимое сообщения")
                    raise HTTPException(
                        status_code=400, 
                        detail="Не указан номер получателя или содержимое сообщения"
                    )
                
                if self.sip_gateway and self.sip_gateway.sip_client:
                    success = await self.sip_gateway.sip_client.send_message(to_number, content)
                    if success:
                        self.logger.outgoing_info(f"Сообщение отправлено на номер {to_number}")
                        return {"message": f"Сообщение отправлено на номер {to_number}"}
                    else:
                        self.logger.outgoing_error("Ошибка отправки сообщения")
                        raise HTTPException(status_code=500, detail="Ошибка отправки сообщения")
                else:
                    self.logger.outgoing_error("SIP клиент не доступен")
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка отправки сообщения: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/audio/info")
        async def get_audio_info():
            """Get audio device information"""
            self.logger.incoming_info("GET /api/audio/info - запрос информации об аудио")
            try:
                if self.sip_gateway and self.sip_gateway.audio_handler:
                    info = self.sip_gateway.audio_handler.get_audio_info()
                    self.logger.outgoing_info("Успешное получение информации об аудио")
                    return info
                else:
                    self.logger.outgoing_error("Audio handler не доступен")
                    raise HTTPException(status_code=500, detail="Audio handler not available")
                    
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка получения информации об аудио: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/logs")
        async def get_logs(limit: int = 100):
            """Get recent logs"""
            self.logger.incoming_info(f"GET /api/logs - запрос логов (limit={limit})")
            try:
                log_file = self.config.get("log_file", "logs/gateway.log")
                if not os.path.exists(log_file):
                    self.logger.outgoing_warning("Файл логов не найден")
                    return {"logs": [], "message": "Файл логов не найден"}
                
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                recent_logs = lines[-limit:] if len(lines) > limit else lines
                self.logger.outgoing_info(f"Возвращено {len(recent_logs)} логов из {len(lines)}")
                return {
                    "logs": [line.strip() for line in recent_logs],
                    "total_lines": len(lines),
                    "shown_lines": len(recent_logs)
                }
                
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка чтения логов: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.delete("/api/logs")
        async def clear_logs():
            """Clear log file"""
            self.logger.incoming_info("DELETE /api/logs - очистка логов")
            try:
                log_file = self.config.get("log_file", "logs/gateway.log")
                if os.path.exists(log_file):
                    with open(log_file, 'w', encoding='utf-8') as f:
                        f.write("")
                    self.logger.outgoing_info("Логи очищены через API")
                    return {"message": "Логи очищены"}
                else:
                    self.logger.outgoing_warning("Файл логов не найден")
                    return {"message": "Файл логов не найден"}
                    
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка очистки логов: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        # Serve demo phone page
        @self.app.get("/phone")
        async def serve_phone():
            """Serve demo phone page"""
            self.logger.incoming_info("GET /phone - запрос демо-телефона")
            phone_path = Path("browser_client/index.html")
            if phone_path.exists():
                self.logger.outgoing_info("Отправка демо-телефона")
                return FileResponse(phone_path)
            else:
                self.logger.outgoing_error("Страница демо-телефона не найдена")
                raise HTTPException(status_code=404, detail="Demo phone page not found")
        
        # Serve static files for demo phone
        static_path = Path("browser_client")
        if static_path.exists():
            self.app.mount("/static", StaticFiles(directory=static_path), name="static")
            self.logger.outgoing_info("Статические файлы демо-телефона подключены")
        
        # Health check
        @self.app.get("/health")
        async def health_check():
            self.logger.incoming_debug("GET /health - проверка здоровья")
            return {"status": "healthy", "timestamp": asyncio.get_event_loop().time()}
    
    async def _register_sip_task(self):
        """Background task for SIP registration"""
        try:
            if self.sip_gateway and self.sip_gateway.sip_client:
                sip_settings = self.config.get("sip_settings")
                if sip_settings:
                    self.logger.outgoing_info("Запуск фоновой регистрации SIP")
                    await self.sip_gateway.sip_client.register(**sip_settings)
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка фоновой регистрации SIP: {e}")
    
    async def _restart_sip_registration(self):
        """Restart SIP registration with new settings"""
        try:
            if self.sip_gateway and self.sip_gateway.sip_client:
                self.logger.outgoing_info("Перезапуск регистрации SIP с новыми настройками")
                # Disconnect current connection
                await self.sip_gateway.sip_client.disconnect()
                # Wait a bit
                await asyncio.sleep(2)
                # Reconnect with new settings
                sip_settings = self.config.get("sip_settings")
                await self.sip_gateway.sip_client.register(**sip_settings)
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка перезапуска SIP регистрации: {e}")
    
    async def start(self):
        """Start REST API server"""
        try:
            config = uvicorn.Config(
                self.app,
                host=self.host,
                port=self.port,
                log_level="info"
            )
            self.server = uvicorn.Server(config)
            
            self.logger.outgoing_info(f"REST API сервер запущен на http://{self.host}:{self.port}")
            await self.server.serve()
            
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка запуска REST API: {e}")
            raise
    
    async def stop(self):
        """Stop REST API server"""
        try:
            if hasattr(self, 'server'):
                self.server.should_exit = True
            self.logger.outgoing_info("REST API сервер остановлен")
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка остановки REST API: {e}")