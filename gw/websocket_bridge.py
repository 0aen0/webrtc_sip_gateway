import asyncio
import json
import logging
from typing import Dict, Set, Optional
from websockets.server import WebSocketServerProtocol, serve
from websockets.exceptions import ConnectionClosed

class WebSocketBridge:
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.connected_clients: Set[WebSocketServerProtocol] = set()
        self.sip_handlers = {}
        self.logger = logging.getLogger("websocket_bridge")
        
        # Статус подключения к SIP
        self.sip_connected = False
        self.sip_registered = False
        
    def set_sip_client(self, sip_client):
        """Установить ссылку на SIP клиент для обратной связи"""
        self.sip_client = sip_client
        
    async def start_server(self):
        """Запуск WebSocket сервера"""
        try:
            self.server = await serve(
                self.handle_connection,
                self.host,
                self.port
            )
            self.logger.info(f"WebSocket сервер запущен на ws://{self.host}:{self.port}")
            
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"WebSocket сервер детали: host={self.host}, port={self.port}")
                
            return True
        except Exception as e:
            self.logger.error(f"Ошибка запуска WebSocket сервера: {e}")
            return False
            
    async def stop_server(self):
        """Остановка WebSocket сервера"""
        if hasattr(self, 'server'):
            self.server.close()
            await self.server.wait_closed()
            self.logger.info("WebSocket сервер остановлен")
        
    async def handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        """Обработка нового подключения"""
        client_id = id(websocket)
        self.connected_clients.add(websocket)
        
        client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        self.logger.incoming_info(f"Новое WebSocket подключение: {client_info} (ID: {client_id})")
        
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.incoming_debug(f"WebSocket детали подключения: path={path}, headers={websocket.request_headers}")
        
        try:
            # Отправляем текущий статус SIP
            await self.send_status_update(websocket)
            
            # Обрабатываем сообщения от клиента
            async for message in websocket:
                await self.handle_message(message, websocket, client_info)
                
        except ConnectionClosed:
            self.logger.incoming_info(f"WebSocket соединение закрыто: {client_info}")
        except Exception as e:
            self.logger.incoming_error(f"Ошибка в WebSocket соединении {client_info}: {e}")
        finally:
            if websocket in self.connected_clients:
                self.connected_clients.remove(websocket)
            self.logger.incoming_info(f"WebSocket подключение завершено: {client_info}")
            
    async def handle_message(self, message: str, websocket: WebSocketServerProtocol, client_info: str):
        """Обработка сообщения от клиента"""
        try:
            data = json.loads(message)
            message_type = data.get("type")
            payload = data.get("payload", {})
            
            self.logger.incoming_info(f"WebSocket сообщение от {client_info}: {message_type}")
            
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.incoming_debug(f"Детали сообщения от {client_info}: type={message_type}, payload={payload}")
            
            # Маршрутизация сообщений
            handlers = {
                "sip_register": self.handle_sip_register,
                "sip_unregister": self.handle_sip_unregister,
                "sip_make_call": self.handle_make_call,
                "sip_answer_call": self.handle_answer_call,
                "sip_hangup_call": self.handle_hangup_call,
                "sip_send_dtmf": self.handle_send_dtmf,
                "sip_send_message": self.handle_send_message,
                "get_status": self.handle_get_status,
                "ping": self.handle_ping
            }
            
            handler = handlers.get(message_type)
            if handler:
                await handler(payload, websocket, client_info)
            else:
                self.logger.incoming_warning(f"Неизвестный тип сообщения от {client_info}: {message_type}")
                await self.send_error(websocket, f"Неизвестный тип сообщения: {message_type}")
                
        except json.JSONDecodeError as e:
            self.logger.incoming_error(f"Ошибка JSON от {client_info}: {e}, сообщение: {message}")
            await self.send_error(websocket, f"Ошибка JSON: {e}")
        except Exception as e:
            self.logger.incoming_error(f"Ошибка обработки сообщения от {client_info}: {e}")
            await self.send_error(websocket, f"Внутренняя ошибка: {e}")
    
    # === Обработчики SIP сообщений ===
    
    async def handle_sip_register(self, payload: Dict, websocket: WebSocketServerProtocol, client_info: str):
        """Регистрация на SIP сервере"""
        try:
            required_fields = ["sip_server", "sip_port", "login", "password", "number"]
            for field in required_fields:
                if field not in payload:
                    self.logger.incoming_warning(f"Отсутствует обязательное поле {field} в запросе от {client_info}")
                    await self.send_error(websocket, f"Отсутствует обязательное поле: {field}")
                    return
            
            self.logger.incoming_info(f"Запрос регистрации SIP от {client_info}: server={payload['sip_server']}:{payload['sip_port']}")
            
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.incoming_debug(f"Детали регистрации SIP от {client_info}: login={payload['login']}, number={payload['number']}")
            
            # Передаем настройки в SIP клиент
            if hasattr(self, 'sip_client') and self.sip_client:
                success = await self.sip_client.register(
                    sip_server=payload["sip_server"],
                    sip_port=payload["sip_port"],
                    login=payload["login"],
                    password=payload["password"],
                    number=payload["number"]
                )
                
                if success:
                    self.logger.outgoing_info(f"Успешная регистрация SIP для {client_info}")
                    await self.send_success(websocket, "SIP регистрация запущена")
                else:
                    self.logger.outgoing_error(f"Ошибка SIP регистрации для {client_info}")
                    await self.send_error(websocket, "Ошибка SIP регистрации")
            else:
                self.logger.outgoing_error(f"SIP клиент не инициализирован для запроса от {client_info}")
                await self.send_error(websocket, "SIP клиент не инициализирован")
                
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка обработки SIP регистрации от {client_info}: {e}")
            await self.send_error(websocket, f"Ошибка регистрации: {e}")
    
    async def handle_sip_unregister(self, payload: Dict, websocket: WebSocketServerProtocol, client_info: str):
        """Отмена регистрации на SIP сервере"""
        try:
            self.logger.incoming_info(f"Запрос отмены регистрации SIP от {client_info}")
            
            if hasattr(self, 'sip_client') and self.sip_client:
                await self.sip_client.disconnect()
                self.logger.outgoing_info(f"Отмена регистрации SIP выполнена для {client_info}")
                await self.send_success(websocket, "Отмена регистрации SIP выполнена")
            else:
                self.logger.outgoing_error(f"SIP клиент не инициализирован для запроса отмены регистрации от {client_info}")
                await self.send_error(websocket, "SIP клиент не инициализирован")
                
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка отмены регистрации SIP от {client_info}: {e}")
            await self.send_error(websocket, f"Ошибка отмены регистрации: {e}")
    
    async def handle_make_call(self, payload: Dict, websocket: WebSocketServerProtocol, client_info: str):
        """Совершение исходящего звонка"""
        try:
            number = payload.get("number")
            if not number:
                self.logger.incoming_warning(f"Не указан номер для вызова от {client_info}")
                await self.send_error(websocket, "Не указан номер для вызова")
                return
                
            self.logger.incoming_info(f"Запрос вызова от {client_info}: номер {number}")
                
            if hasattr(self, 'sip_client') and self.sip_client and self.sip_client.is_registered:
                success = await self.sip_client.make_call(number)
                if success:
                    self.logger.outgoing_info(f"Вызов установлен для {client_info}: {number}")
                    await self.send_success(websocket, f"Вызов номера {number}")
                else:
                    self.logger.outgoing_error(f"Ошибка вызова для {client_info}: {number}")
                    await self.send_error(websocket, f"Ошибка вызова номера {number}")
            else:
                self.logger.outgoing_warning(f"SIP клиент не зарегистрирован для запроса вызова от {client_info}")
                await self.send_error(websocket, "SIP клиент не зарегистрирован")
                
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка совершения вызова от {client_info}: {e}")
            await self.send_error(websocket, f"Ошибка вызова: {e}")
    
    async def handle_answer_call(self, payload: Dict, websocket: WebSocketServerProtocol, client_info: str):
        """Ответ на входящий звонка"""
        try:
            self.logger.incoming_info(f"Запрос ответа на звонок от {client_info}")
            
            if hasattr(self, 'sip_client') and self.sip_client:
                success = await self.sip_client.answer_call()
                if success:
                    self.logger.outgoing_info(f"Звонок принят для {client_info}")
                    await self.send_success(websocket, "Звонок принят")
                else:
                    self.logger.outgoing_error(f"Ошибка приема звонка для {client_info}")
                    await self.send_error(websocket, "Ошибка приема звонка")
            else:
                self.logger.outgoing_error(f"SIP клиент не инициализирован для запроса ответа от {client_info}")
                await self.send_error(websocket, "SIP клиент не инициализирован")
                
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка ответа на звонок от {client_info}: {e}")
            await self.send_error(websocket, f"Ошибка ответа: {e}")
    
    async def handle_hangup_call(self, payload: Dict, websocket: WebSocketServerProtocol, client_info: str):
        """Завершение звонка"""
        try:
            self.logger.incoming_info(f"Запрос завершения звонка от {client_info}")
            
            if hasattr(self, 'sip_client') and self.sip_client:
                success = await self.sip_client.hangup_call()
                if success:
                    self.logger.outgoing_info(f"Звонок завершен для {client_info}")
                    await self.send_success(websocket, "Звонок завершен")
                else:
                    self.logger.outgoing_error(f"Ошибка завершения звонка для {client_info}")
                    await self.send_error(websocket, "Ошибка завершения звонка")
            else:
                self.logger.outgoing_error(f"SIP клиент не инициализирован для запроса завершения от {client_info}")
                await self.send_error(websocket, "SIP клиент не инициализирован")
                
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка завершения звонка от {client_info}: {e}")
            await self.send_error(websocket, f"Ошибка завершения: {e}")
    
    async def handle_send_dtmf(self, payload: Dict, websocket: WebSocketServerProtocol, client_info: str):
        """Отправка DTMF сигнала"""
        try:
            digit = payload.get("digit")
            if not digit:
                self.logger.incoming_warning(f"Не указана DTMF цифра от {client_info}")
                await self.send_error(websocket, "Не указана DTMF цифра")
                return
                
            self.logger.incoming_info(f"Запрос отправки DTMF от {client_info}: {digit}")
                
            if hasattr(self, 'sip_client') and self.sip_client:
                success = await self.sip_client.send_dtmf(digit)
                if success:
                    self.logger.outgoing_info(f"DTMF отправлен для {client_info}: {digit}")
                    await self.send_success(websocket, f"DTMF отправлен: {digit}")
                else:
                    self.logger.outgoing_error(f"Ошибка отправки DTMF для {client_info}: {digit}")
                    await self.send_error(websocket, f"Ошибка отправки DTMF: {digit}")
            else:
                self.logger.outgoing_error(f"SIP клиент не инициализирован для запроса DTMF от {client_info}")
                await self.send_error(websocket, "SIP клиент не инициализирован")
                
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка отправки DTMF от {client_info}: {e}")
            await self.send_error(websocket, f"Ошибка DTMF: {e}")

    async def handle_send_message(self, payload: Dict, websocket: WebSocketServerProtocol, client_info: str):
        """Отправка SIP MESSAGE с авторизацией"""
        try:
            to_number = payload.get("to_number")
            content = payload.get("content")
            
            if not to_number or not content:
                self.logger.incoming_warning(f"Не указан номер или содержимое сообщения от {client_info}")
                await self.send_error(websocket, "Не указан номер или содержимое сообщения")
                return
            
            self.logger.incoming_info(f"Запрос отправки сообщения от {client_info}: номер {to_number}")
            
            if hasattr(self, 'sip_client') and self.sip_client and self.sip_client.is_registered:
                success = await self.sip_client.send_message(to_number, content)
                if success:
                    self.logger.outgoing_info(f"Сообщение отправлено для {client_info}: {to_number}")
                    await self.send_success(websocket, f"Сообщение отправлено на номер {to_number}")
                else:
                    self.logger.outgoing_error(f"Ошибка отправки сообщения для {client_info}: {to_number}")
                    await self.send_error(websocket, f"Ошибка отправки сообщения на номер {to_number}")
            else:
                self.logger.outgoing_warning(f"SIP клиент не зарегистрирован для отправки сообщения от {client_info}")
                await self.send_error(websocket, "SIP клиент не зарегистрирован")
                
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка отправки сообщения от {client_info}: {e}")
            await self.send_error(websocket, f"Ошибка отправки сообщения: {e}")
    
    async def handle_get_status(self, payload: Dict, websocket: WebSocketServerProtocol, client_info: str):
        """Запрос статуса"""
        self.logger.incoming_info(f"Запрос статуса от {client_info}")
        await self.send_status_update(websocket)
    
    async def handle_ping(self, payload: Dict, websocket: WebSocketServerProtocol, client_info: str):
        """Обработка ping-сообщения"""
        self.logger.incoming_debug(f"Ping от {client_info}")
        await self.send_message(websocket, {
            "type": "pong",
            "payload": {"timestamp": payload.get("timestamp")}
        })
    
    # === Методы отправки сообщений ===
    
    async def send_message(self, websocket: WebSocketServerProtocol, message: Dict):
        """Отправка сообщения конкретному клиенту"""
        try:
            message_str = json.dumps(message, ensure_ascii=False)
            await websocket.send(message_str)
            
            message_type = message.get('type', 'unknown')
            self.logger.outgoing_info(f"WebSocket сообщение {message_type}")
            
            if self.logger.isEnabledFor(logging.DEBUG):
                client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
                self.logger.outgoing_debug(f"Детали сообщения для {client_info}: {message}")
                
        except ConnectionClosed:
            self.logger.outgoing_warning("Попытка отправки на закрытое соединение")
        except Exception as e:
            self.logger.outgoing_error(f"Ошибка отправки сообщения: {e}")
    
    async def broadcast_message(self, message: Dict):
        """Широковещательная отправка сообщения всем клиентам"""
        if not self.connected_clients:
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.outgoing_debug("Нет подключенных клиентов для широковещательной отправки")
            return
            
        disconnected_clients = []
        message_type = message.get("type", "unknown")
        
        self.logger.outgoing_info(f"Широковещательная отправка {message_type} для {len(self.connected_clients)} клиентов")
        
        for client in self.connected_clients:
            try:
                await client.send(json.dumps(message, ensure_ascii=False))
            except ConnectionClosed:
                disconnected_clients.append(client)
            except Exception as e:
                self.logger.outgoing_error(f"Ошибка широковещательной отправки: {e}")
                disconnected_clients.append(client)
        
        # Удаляем отключенных клиентов
        for client in disconnected_clients:
            if client in self.connected_clients:
                self.connected_clients.remove(client)
                self.logger.outgoing_info(f"Удален отключенный клиент из широковещательной рассылки")
    
    async def send_success(self, websocket: WebSocketServerProtocol, message: str):
        """Отправка сообщения об успехе"""
        await self.send_message(websocket, {
            "type": "success",
            "payload": {"message": message}
        })
    
    async def send_error(self, websocket: WebSocketServerProtocol, message: str):
        """Отправка сообщения об ошибке"""
        await self.send_message(websocket, {
            "type": "error",
            "payload": {"message": message}
        })
    
    async def send_status_update(self, websocket: WebSocketServerProtocol = None):
        """Отправка обновления статуса"""
        sip_client = getattr(self, 'sip_client', None)
        status_message = {
            "type": "status_update",
            "payload": {
                "websocket_connected": True,
                "sip_connected": self.sip_connected,
                "sip_registered": self.sip_registered,
                "active_call": getattr(sip_client, 'active_call', False) if sip_client else False,
                "has_incoming": getattr(sip_client, 'incoming_call', False) if sip_client else False,
                "caller_number": getattr(sip_client, 'caller_number', '') if sip_client else '',
                "connected_clients": len(self.connected_clients),
                "timestamp": asyncio.get_event_loop().time()
            }
        }
        
        self.logger.outgoing_info(f"Отправка статуса: registered={self.sip_registered}, in_call={getattr(sip_client, 'active_call', False)}, clients={len(self.connected_clients)}")
        
        if websocket:
            await self.send_message(websocket, status_message)
        else:
            await self.broadcast_message(status_message)
    
    # === Методы для уведомлений от SIP клиента ===
    
    async def notify_sip_registered(self):
        """Уведомление о успешной регистрации SIP"""
        self.sip_registered = True
        self.logger.outgoing_info("Уведомление о регистрации SIP отправлено всем клиентам")
        await self.broadcast_message({
            "type": "sip_registered",
            "payload": {"message": "Успешная регистрация на SIP сервере"}
        })
        await self.send_status_update()
    
    async def notify_sip_unregistered(self):
        """Уведомление о снятии регистрации SIP"""
        self.sip_registered = False
        self.logger.outgoing_info("Уведомление о снятии регистрации SIP отправлено всем клиентам")
        await self.broadcast_message({
            "type": "sip_unregistered",
            "payload": {"message": "Регистрация SIP сброшена"}
        })
        await self.send_status_update()
    
    async def notify_incoming_call(self, caller_number: str):
        """Уведомление о входящем звонке"""
        self.logger.outgoing_info(f"Уведомление о входящем звонке от {caller_number} отправлено всем клиентам")
        await self.broadcast_message({
            "type": "incoming_call",
            "payload": {
                "caller_number": caller_number,
                "timestamp": asyncio.get_event_loop().time()
            }
        })
    
    async def notify_call_answered(self):
        """Уведомление о принятом звонке"""
        self.logger.outgoing_info("Уведомление о принятом звонке отправлено всем клиентам")
        await self.broadcast_message({
            "type": "call_answered",
            "payload": {
                "message": "Звонок принят",
                "timestamp": asyncio.get_event_loop().time()
            }
        })
    
    async def notify_call_ended(self, reason: str = ""):
        """Уведомление о завершении звонка"""
        self.logger.outgoing_info("Уведомление о завершении звонка отправлено всем клиентам")
        await self.broadcast_message({
            "type": "call_ended",
            "payload": {
                "message": "Звонок завершен",
                "reason": reason,
                "timestamp": asyncio.get_event_loop().time()
            }
        })
    
    async def notify_call_failed(self, reason: str):
        """Уведомление о неудачном звонке"""
        self.logger.outgoing_error(f"Уведомление о неудачном звонке: {reason}")
        await self.broadcast_message({
            "type": "call_failed",
            "payload": {
                "message": "Ошибка звонка",
                "reason": reason,
                "timestamp": asyncio.get_event_loop().time()
            }
        })

    async def notify_call_ringing(self):
        """Уведомление о том, что абонент звонит (получен 180 Ringing)"""
        self.logger.outgoing_info("Уведомление о звонке абонента отправлено всем клиентам")
        await self.broadcast_message({
            "type": "call_ringing", 
            "payload": {
                "message": "Абонент звонит",
                "timestamp": asyncio.get_event_loop().time()
            }
        })
    
    def get_connection_count(self) -> int:
        """Получить количество подключенных клиентов"""
        count = len(self.connected_clients)
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"Текущее количество подключенных клиентов: {count}")
        return count
    
    def get_connection_info(self) -> list:
        """Получить информацию о подключенных клиентах"""
        clients_info = []
        for client in self.connected_clients:
            try:
                clients_info.append(f"{client.remote_address[0]}:{client.remote_address[1]}")
            except:
                clients_info.append("unknown")
        return clients_info

    def get_websocket_status(self) -> Dict:
        """Получить статус WebSocket сервера"""
        return {
            "host": self.host,
            "port": self.port,
            "connected_clients": len(self.connected_clients),
            "sip_registered": self.sip_registered,
            "sip_connected": self.sip_connected,
            "clients_info": self.get_connection_info()
        }

    async def close_all_connections(self):
        """Закрыть все WebSocket соединения"""
        if not self.connected_clients:
            return
            
        self.logger.info(f"Закрытие всех WebSocket соединений ({len(self.connected_clients)} клиентов)")
        
        disconnected_clients = []
        for client in self.connected_clients:
            try:
                await client.close()
                disconnected_clients.append(client)
            except Exception as e:
                self.logger.error(f"Ошибка закрытия соединения с клиентом: {e}")
        
        # Удаляем закрытые соединения
        for client in disconnected_clients:
            if client in self.connected_clients:
                self.connected_clients.remove(client)
        
        self.logger.info(f"Закрыто {len(disconnected_clients)} WebSocket соединений")