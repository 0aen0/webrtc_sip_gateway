import asyncio
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn
import os
from pathlib import Path
import json

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
        """Setup CORS and other middleware"""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
    def setup_routes(self):
        """Setup API routes"""
        
        @self.app.get("/")
        async def root():
            return {
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
        
        @self.app.get("/api/status")
        async def get_status():
            """Get gateway status"""
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
                return status
            except Exception as e:
                self.logger.error(f"Ошибка получения статуса: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/settings")
        async def get_settings():
            """Get current settings"""
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
                return settings
            except Exception as e:
                self.logger.error(f"Ошибка получения настроек: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.put("/api/settings")
        async def update_settings(settings: Dict[str, Any]):
            """Update gateway settings"""
            try:
                # Validate required SIP fields if provided
                if "sip_settings" in settings:
                    sip_settings = settings["sip_settings"]
                    required_fields = ["sip_server", "login", "password", "number"]
                    
                    for field in required_fields:
                        if field not in sip_settings or not sip_settings[field]:
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
                    self.logger.info("Настройки успешно обновлены")
                    
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
                    raise HTTPException(status_code=500, detail="Ошибка сохранения настроек")
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.error(f"Ошибка обновления настроек: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.put("/api/logging/level")
        async def update_log_level(payload: Dict[str, str]):
            """Update log level"""
            try:
                log_level = payload.get("level", "INFO").upper()
                valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
                
                if log_level not in valid_levels:
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
                
                self.logger.info(f"Уровень логирования изменен на: {log_level}")
                
                return {"message": f"Уровень логирования изменен на {log_level}", "level": log_level}
                
            except Exception as e:
                self.logger.error(f"Ошибка изменения уровня логирования: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/logging/level")
        async def get_log_level():
            """Get current log level"""
            try:
                level = self.config.get("log_level", "INFO")
                return {"level": level}
            except Exception as e:
                self.logger.error(f"Ошибка получения уровня логирования: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/sip/register")
        async def register_sip(background_tasks: BackgroundTasks):
            """Register on SIP server with current settings"""
            try:
                sip_settings = self.config.get("sip_settings")
                if not all([sip_settings.get("sip_server"), sip_settings.get("login"), 
                           sip_settings.get("password"), sip_settings.get("number")]):
                    raise HTTPException(
                        status_code=400, 
                        detail="Не все SIP настройки заполнены"
                    )
                
                if self.sip_gateway and self.sip_gateway.sip_client:
                    background_tasks.add_task(self._register_sip_task)
                    return {"message": "Запущена регистрация на SIP сервере"}
                else:
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except Exception as e:
                self.logger.error(f"Ошибка регистрации SIP: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/sip/unregister")
        async def unregister_sip():
            """Unregister from SIP server"""
            try:
                if self.sip_gateway and self.sip_gateway.sip_client:
                    await self.sip_gateway.sip_client.disconnect()
                    return {"message": "Отключение от SIP сервера выполнено"}
                else:
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except Exception as e:
                self.logger.error(f"Ошибка отключения SIP: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/sip/status")
        async def get_sip_status():
            """Get SIP client status"""
            try:
                if self.sip_gateway and self.sip_gateway.sip_client:
                    status = self.sip_gateway.sip_client.get_status()
                    return status
                else:
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except Exception as e:
                self.logger.error(f"Ошибка получения статуса SIP: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/call/make")
        async def make_call(payload: Dict[str, str]):
            """Make outgoing call"""
            try:
                number = payload.get("number")
                if not number:
                    raise HTTPException(status_code=400, detail="Не указан номер")
                
                if self.sip_gateway and self.sip_gateway.sip_client:
                    success = await self.sip_gateway.sip_client.make_call(number)
                    if success:
                        return {"message": f"Вызов номера {number} initiated"}
                    else:
                        raise HTTPException(status_code=500, detail="Ошибка совершения вызова")
                else:
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.error(f"Ошибка совершения вызова: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/call/answer")
        async def answer_call():
            """Answer incoming call"""
            try:
                if self.sip_gateway and self.sip_gateway.sip_client:
                    success = await self.sip_gateway.sip_client.answer_call()
                    if success:
                        return {"message": "Звонок принят"}
                    else:
                        raise HTTPException(status_code=500, detail="Ошибка приема звонка")
                else:
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.error(f"Ошибка приема звонка: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/call/hangup")
        async def hangup_call():
            """Hang up current call"""
            try:
                if self.sip_gateway and self.sip_gateway.sip_client:
                    success = await self.sip_gateway.sip_client.hangup_call()
                    if success:
                        return {"message": "Звонок завершен"}
                    else:
                        raise HTTPException(status_code=500, detail="Ошибка завершения звонка")
                else:
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.error(f"Ошибка завершения звонка: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/call/dtmf")
        async def send_dtmf(payload: Dict[str, str]):
            """Send DTMF tone"""
            try:
                digit = payload.get("digit")
                if not digit:
                    raise HTTPException(status_code=400, detail="Не указана цифра DTMF")
                
                if self.sip_gateway and self.sip_gateway.sip_client:
                    success = await self.sip_gateway.sip_client.send_dtmf(digit)
                    if success:
                        return {"message": f"DTMF отправлен: {digit}"}
                    else:
                        raise HTTPException(status_code=500, detail="Ошибка отправки DTMF")
                else:
                    raise HTTPException(status_code=500, detail="SIP клиент не доступен")
                    
            except HTTPException:
                raise
            except Exception as e:
                self.logger.error(f"Ошибка отправки DTMF: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/audio/info")
        async def get_audio_info():
            """Get audio device information"""
            try:
                if self.sip_gateway and self.sip_gateway.audio_handler:
                    info = self.sip_gateway.audio_handler.get_audio_info()
                    return info
                else:
                    raise HTTPException(status_code=500, detail="Audio handler not available")
                    
            except Exception as e:
                self.logger.error(f"Ошибка получения информации об аудио: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/logs")
        async def get_logs(limit: int = 100):
            """Get recent logs"""
            try:
                log_file = self.config.get("log_file", "logs/gateway.log")
                if not os.path.exists(log_file):
                    return {"logs": [], "message": "Файл логов не найден"}
                
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                recent_logs = lines[-limit:] if len(lines) > limit else lines
                return {
                    "logs": [line.strip() for line in recent_logs],
                    "total_lines": len(lines),
                    "shown_lines": len(recent_logs)
                }
                
            except Exception as e:
                self.logger.error(f"Ошибка чтения логов: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.delete("/api/logs")
        async def clear_logs():
            """Clear log file"""
            try:
                log_file = self.config.get("log_file", "logs/gateway.log")
                if os.path.exists(log_file):
                    with open(log_file, 'w', encoding='utf-8') as f:
                        f.write("")
                    self.logger.info("Логи очищены через API")
                    return {"message": "Логи очищены"}
                else:
                    return {"message": "Файл логов не найден"}
                    
            except Exception as e:
                self.logger.error(f"Ошибка очистки логов: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        # Serve demo phone page
        @self.app.get("/phone")
        async def serve_phone():
            """Serve demo phone page"""
            phone_path = Path("browser_client/index.html")
            if phone_path.exists():
                return FileResponse(phone_path)
            else:
                raise HTTPException(status_code=404, detail="Demo phone page not found")
        
        # Serve static files for demo phone
        static_path = Path("browser_client")
        if static_path.exists():
            self.app.mount("/static", StaticFiles(directory=static_path), name="static")
        
        # Health check
        @self.app.get("/health")
        async def health_check():
            return {"status": "healthy", "timestamp": asyncio.get_event_loop().time()}
    
    async def _register_sip_task(self):
        """Background task for SIP registration"""
        try:
            if self.sip_gateway and self.sip_gateway.sip_client:
                sip_settings = self.config.get("sip_settings")
                if sip_settings:
                    await self.sip_gateway.sip_client.register(**sip_settings)
        except Exception as e:
            self.logger.error(f"Ошибка фоновой регистрации SIP: {e}")
    
    async def _restart_sip_registration(self):
        """Restart SIP registration with new settings"""
        try:
            if self.sip_gateway and self.sip_gateway.sip_client:
                # Disconnect current connection
                await self.sip_gateway.sip_client.disconnect()
                # Wait a bit
                await asyncio.sleep(2)
                # Reconnect with new settings
                sip_settings = self.config.get("sip_settings")
                await self.sip_gateway.sip_client.register(**sip_settings)
        except Exception as e:
            self.logger.error(f"Ошибка перезапуска SIP регистрации: {e}")
    
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
            
            self.logger.info(f"REST API сервер запущен на http://{self.host}:{self.port}")
            await self.server.serve()
            
        except Exception as e:
            self.logger.error(f"Ошибка запуска REST API: {e}")
            raise
    
    async def stop(self):
        """Stop REST API server"""
        try:
            if hasattr(self, 'server'):
                self.server.should_exit = True
            self.logger.info("REST API сервер остановлен")
        except Exception as e:
            self.logger.error(f"Ошибка остановки REST API: {e}")