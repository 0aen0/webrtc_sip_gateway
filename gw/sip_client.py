import asyncio
import logging
from typing import Dict, Optional
import socket
import hashlib
import random
import re
from threading import Thread
import time
import select
import queue
import string
import json
import os

class SIPClient:
    def __init__(self):
        self.registered = False
        self.active_call = False
        self.incoming_call = False
        self.caller_number = ""
        self.current_call_id = None
        self.dialed_number = ""
        
        self.websocket_bridge = None
        self.logger = logging.getLogger("sip_client")
        self.sip_config = {}
        self.sip_socket = None
        self.running = False
        
        # Authentication state
        self.auth_nonce = None
        self.auth_realm = None
        self.auth_opaque = None
        self.auth_qop = None
        self.auth_cache_file = "sip_auth_cache.json"
        
        # SIP session state
        self.cseq_counter = 1
        self.call_id = None
        self.from_tag = None
        self.to_tag = None
        
        # Message queue for thread-safe communication
        self.message_queue = queue.Queue()
        
        # Keep track of registration
        self.last_register_time = 0
        self.register_expires = 300
        
        # Statistics
        self.messages_received = 0
        self.messages_sent = 0
        
        # OPTIONS tracking
        self.last_options_response = 0
        self.options_timeout = 30  # seconds
        
        # Event loop for thread-safe async operations
        self.main_event_loop = None
        
        # Call state
        self.call_state = "IDLE"  # IDLE, DIALING, RINGING, ACTIVE, HANGING_UP
        self.remote_sdp = None
        self.local_sdp = None
        
        # Load cached authentication
        self.load_auth_cache()
        
    def set_websocket_bridge(self, websocket_bridge):
        """Set reference to WebSocket bridge for callbacks"""
        self.websocket_bridge = websocket_bridge
        # Store the main event loop when WebSocket bridge is set
        try:
            self.main_event_loop = asyncio.get_event_loop()
        except RuntimeError:
            # If there's no current event loop, we'll handle it differently
            pass

    def load_auth_cache(self):
        """Load cached authentication data from file"""
        try:
            if os.path.exists(self.auth_cache_file):
                with open(self.auth_cache_file, 'r') as f:
                    auth_cache = json.load(f)
                    self.auth_realm = auth_cache.get('realm')
                    self.auth_nonce = auth_cache.get('nonce')
                    self.auth_opaque = auth_cache.get('opaque')
                    self.auth_qop = auth_cache.get('qop')
                    self.logger.info("Загружены кэшированные данные аутентификации")
        except Exception as e:
            self.logger.warning(f"Не удалось загрузить кэш аутентификации: {e}")

    def save_auth_cache(self):
        """Save authentication data to cache file"""
        try:
            auth_cache = {
                'realm': self.auth_realm,
                'nonce': self.auth_nonce,
                'opaque': self.auth_opaque,
                'qop': self.auth_qop,
                'timestamp': time.time()
            }
            with open(self.auth_cache_file, 'w') as f:
                json.dump(auth_cache, f)
            self.logger.debug("Данные аутентификации сохранены в кэш")
        except Exception as e:
            self.logger.warning(f"Не удалось сохранить кэш аутентификации: {e}")

    def clear_auth_cache(self):
        """Clear authentication cache"""
        try:
            if os.path.exists(self.auth_cache_file):
                os.remove(self.auth_cache_file)
                self.logger.info("Кэш аутентификации очищен")
        except Exception as e:
            self.logger.warning(f"Не удалось очистить кэш аутентификации: {e}")

    def has_cached_auth(self):
        """Check if we have cached authentication data"""
        return all([self.auth_realm, self.auth_nonce, self.auth_opaque])
        
    async def register(self, sip_server: str, sip_port: int, login: str, 
                      password: str, number: str) -> bool:
        """Register on SIP server using raw sockets"""
        try:
            self.sip_config = {
                'sip_server': sip_server,
                'sip_port': sip_port,
                'login': login,
                'password': password,
                'number': number
            }
            
            self.logger.info(f"Регистрация на SIP сервере {sip_server}:{sip_port} как {number}")
            
            # Store main event loop
            self.main_event_loop = asyncio.get_event_loop()
            
            # Create UDP socket
            self.sip_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sip_socket.settimeout(10.0)
            
            # Initialize SIP session
            self.call_id = self._generate_call_id()
            self.from_tag = self._generate_tag()
            self.cseq_counter = 1
            
            # Start message processing threads
            self.running = True
            self.receiving_thread = Thread(target=self._receiving_loop, daemon=True)
            self.processing_thread = Thread(target=self._processing_loop, daemon=True)
            self.keepalive_thread = Thread(target=self._keepalive_loop, daemon=True)
            
            self.receiving_thread.start()
            self.processing_thread.start()
            self.keepalive_thread.start()
            
            # Try to register with cached auth first
            if self.has_cached_auth():
                self.logger.info("Попытка регистрации с кэшированными данными аутентификации")
                self.cseq_counter += 1
                self._send_register_sync(with_auth=True)
                
                # Wait for registration with cached auth
                for i in range(10):  # 10 seconds timeout for cached auth
                    if self.registered:
                        self.logger.info("Успешная регистрация с кэшированной аутентификацией")
                        if self.websocket_bridge:
                            await self.websocket_bridge.notify_sip_registered()
                        return True
                    await asyncio.sleep(1)
                
                self.logger.warning("Кэшированная аутентификация не сработала, пробуем обычную регистрацию")
                self.clear_auth_cache()
            
            # Send initial REGISTER without auth
            if await self._send_initial_register():
                self.logger.info("Начальный REGISTER отправлен")
                
                # Wait for registration with timeout
                for i in range(30):  # 30 seconds timeout
                    if self.registered:
                        self.logger.info("Успешная регистрация SIP")
                        if self.websocket_bridge:
                            await self.websocket_bridge.notify_sip_registered()
                        return True
                    await asyncio.sleep(1)
                
                self.logger.error("Таймаут регистрации SIP")
                return False
            else:
                return False
                
        except Exception as e:
            self.logger.error(f"Ошибка регистрации SIP: {e}")
            return False

    async def make_call(self, number: str) -> bool:
        """Make outgoing call to specified number"""
        try:
            if not self.registered:
                self.logger.error("Не зарегистрирован на SIP сервере")
                if self.websocket_bridge:
                    await self.websocket_bridge.notify_call_failed("Не зарегистрирован на SIP сервере")
                return False
            
            if self.active_call or self.incoming_call:
                self.logger.error("Уже есть активный звонок")
                if self.websocket_bridge:
                    await self.websocket_bridge.notify_call_failed("Уже есть активный звонок")
                return False
            
            self.dialed_number = number
            self.call_state = "DIALING"
            
            self.logger.info(f"Совершение вызова на номер: {number}")
            
            # Generate new call ID and tags for this call
            self.current_call_id = self._generate_call_id()
            self.from_tag = self._generate_tag()
            self.cseq_counter = 1
            
            # Build INVITE message
            invite_msg = self._build_invite_message(number)
            
            # Send INVITE
            server = self.sip_config['sip_server']
            port = self.sip_config['sip_port']
            
            self.logger.debug(f"Отправка INVITE:\n{invite_msg}")
            
            self.sip_socket.sendto(invite_msg.encode(), (server, port))
            self.messages_sent += 1
            
            self.logger.info(f"INVITE отправлен на номер {number}")
            
            # Start call timeout
            asyncio.create_task(self._call_timeout_manager())
            
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка совершения вызова: {e}")
            if self.websocket_bridge:
                await self.websocket_bridge.notify_call_failed(f"Ошибка совершения вызова: {e}")
            return False

    def _build_invite_message(self, number: str) -> str:
        """Build SIP INVITE message with authentication"""
        server = self.sip_config['sip_server']
        local_ip = self._get_local_ip()
        from_number = self.sip_config['number']
        login = self.sip_config['login']
        
        # Generate SIP parameters
        branch = f"z9hG4bK{random.getrandbits(32)}"
        
        # Build SDP body
        sdp_body = self._build_sdp_body(local_ip)
        
        headers = [
            f"INVITE sip:{number}@{server} SIP/2.0",
            f"Via: SIP/2.0/UDP {local_ip}:5060;branch={branch};rport",
            "Max-Forwards: 70",
            f"From: <sip:{from_number}@{server}>;tag={self.from_tag}",
            f"To: <sip:{number}@{server}>",
            f"Call-ID: {self.current_call_id}",
            f"CSeq: {self.cseq_counter} INVITE",
            "Contact: <sip:{}@{}:5060;transport=udp>".format(login, local_ip),
            "User-Agent: SIPGateway/1.0",
            "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, SUBSCRIBE, NOTIFY, MESSAGE, INFO",
            "Supported: replaces, timer, outbound, path, gruu",
            "Content-Type: application/sdp",
            f"Content-Length: {len(sdp_body)}"
        ]
        
        # Add Authorization header if we have cached authentication
        if self.has_cached_auth():
            auth_header = self._build_invite_auth_header(number)
            headers.append(auth_header)
            self.logger.debug("Добавлен заголовок Authorization в INVITE")
        
        headers.append("")  # Empty line before body
        headers.append(sdp_body)
        
        return "\r\n".join(headers)

    def _build_invite_auth_header(self, number: str) -> str:
        """Build Authorization header for INVITE request"""
        username = self.sip_config['login']
        realm = self.auth_realm
        nonce = self.auth_nonce
        uri = f"sip:{number}@{self.sip_config['sip_server']}"
        
        # Calculate response for INVITE method
        response, cnonce = self._calculate_sip_response(
            nonce=nonce,
            qop=self.auth_qop,
            method="INVITE",
            uri=uri
        )
        
        self.logger.debug(f"Calculated INVITE response: {response}")
        
        # Build Authorization header according to RFC 2617
        auth_parts = [
            f'Authorization: Digest username="{username}"',
            f'realm="{realm}"',
            f'nonce="{nonce}"',
            f'uri="{uri}"',
            f'response="{response}"'
        ]
        
        # Add mandatory parameters for qop=auth
        if self.auth_qop:
            auth_parts.extend([
                f'qop={self.auth_qop}',
                f'nc=00000001',
                f'cnonce="{cnonce}"'
            ])
        
        if self.auth_opaque:
            auth_parts.append(f'opaque="{self.auth_opaque}"')
        
        # Always include algorithm
        auth_parts.append('algorithm=MD5')
        
        return ", ".join(auth_parts)
    
    def _build_sdp_body(self, local_ip: str) -> str:
        """Build SDP body for INVITE"""
        # Generate random session ID
        session_id = random.getrandbits(32)
        
        sdp = [
            "v=0",
            f"o={self.sip_config['login']} {session_id} {session_id} IN IP4 {local_ip}",
            "s=SIP Gateway Call",
            "c=IN IP4 {}".format(local_ip),
            "t=0 0",
            "m=audio 8000 RTP/AVP 0 8 101",  # PCMU, PCMA, telephone-event
            "a=rtpmap:0 PCMU/8000",
            "a=rtpmap:8 PCMA/8000", 
            "a=rtpmap:101 telephone-event/8000",
            "a=fmtp:101 0-16",
            "a=sendrecv"
        ]
        
        return "\r\n".join(sdp)
    
    async def _call_timeout_manager(self):
        """Manage call timeout - if no response in 30 seconds, cancel call"""
        await asyncio.sleep(30)  # 30 seconds timeout
        
        if self.call_state == "DIALING":
            self.logger.warning("Таймаут вызова - отмена звонка")
            await self.hangup_call()
            if self.websocket_bridge:
                await self.websocket_bridge.notify_call_failed("Таймаут вызова")

    async def send_options(self) -> bool:
        """Send OPTIONS request to server for keepalive"""
        try:
            if not self.sip_socket or not self.registered:
                return False
            
            server = self.sip_config['sip_server']
            port = self.sip_config['sip_port']
            local_ip = self._get_local_ip()
            
            options_msg = self._build_options_message()
            
            self.logger.debug(f"Отправка OPTIONS:\n{options_msg}")
            
            self.sip_socket.sendto(options_msg.encode(), (server, port))
            self.messages_sent += 1
            self.logger.debug("OPTIONS запрос отправлен")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка отправки OPTIONS: {e}")
            return False

    def _send_options_sync(self) -> bool:
        """Send OPTIONS synchronously (for use in threads)"""
        try:
            if not self.sip_socket or not self.registered:
                return False
            
            server = self.sip_config['sip_server']
            port = self.sip_config['sip_port']
            local_ip = self._get_local_ip()
            
            options_msg = self._build_options_message()
            
            self.logger.debug("Отправка OPTIONS (синхронно)")
            
            self.sip_socket.sendto(options_msg.encode(), (server, port))
            self.messages_sent += 1
            self.logger.debug("OPTIONS запрос отправлен (синхронно)")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка отправки OPTIONS (синхронно): {e}")
            return False

    def _build_options_message(self) -> str:
        """Build SIP OPTIONS message"""
        server = self.sip_config['sip_server']
        local_ip = self._get_local_ip()
        number = self.sip_config['number']
        login = self.sip_config['login']
        
        # Generate SIP parameters
        call_id = self._generate_call_id()
        branch = f"z9hG4bK{random.getrandbits(32)}"
        tag = self._generate_tag()
        
        headers = [
            f"OPTIONS sip:{server} SIP/2.0",
            f"Via: SIP/2.0/UDP {local_ip}:5060;branch={branch};rport",
            "Max-Forwards: 70",
            f"From: <sip:{number}@{server}>;tag={tag}",
            f"To: <sip:{number}@{server}>",
            f"Call-ID: {call_id}",
            "CSeq: 1 OPTIONS",
            f"Contact: <sip:{login}@{local_ip}:5060;transport=udp>",
            "User-Agent: SIPGateway/1.0",
            "Accept: application/sdp",
            "Content-Length: 0",
            "",
            ""
        ]
        
        return "\r\n".join(headers)
    
    async def _send_initial_register(self) -> bool:
        """Send initial REGISTER without authentication"""
        try:
            server = self.sip_config['sip_server']
            port = self.sip_config['sip_port']
            local_ip = self._get_local_ip()
            
            register_msg = self._build_register_message()
            
            self.logger.debug(f"Отправка REGISTER:\n{register_msg}")
            
            self.sip_socket.sendto(register_msg.encode(), (server, port))
            self.messages_sent += 1
            self.logger.info(f"REGISTER отправлен на {server}:{port}")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка отправки REGISTER: {e}")
            return False
    
    def _build_register_message(self, with_auth=False) -> str:
        """Build SIP REGISTER message"""
        server = self.sip_config['sip_server']
        local_ip = self._get_local_ip()
        number = self.sip_config['number']
        login = self.sip_config['login']
        
        # Generate SIP parameters
        call_id = self.call_id or f"{random.getrandbits(32)}@{local_ip}"
        branch = f"z9hG4bK{random.getrandbits(32)}"
        tag = self.from_tag or f"{random.getrandbits(32)}"
        
        headers = [
            f"REGISTER sip:{server} SIP/2.0",
            f"Via: SIP/2.0/UDP {local_ip}:5060;branch={branch};rport",
            "Max-Forwards: 70",
            f"From: <sip:{number}@{server}>;tag={tag}",
            f"To: <sip:{number}@{server}>",
            f"Call-ID: {call_id}",
            f"CSeq: {self.cseq_counter} REGISTER",
            f"Contact: <sip:{login}@{local_ip}:5060;transport=udp>;expires={self.register_expires}",
            "User-Agent: SIPGateway/1.0",
            f"Expires: {self.register_expires}",
            "Supported: outbound, path"
        ]
        
        # Add authentication if required
        if with_auth and self.auth_nonce:
            auth_header = self._build_auth_header()
            headers.append(auth_header)
        
        headers.append("Content-Length: 0")
        headers.append("")  # Empty line for end of headers
        
        return "\r\n".join(headers)
    
    def _calculate_sip_response(self, nonce, qop=None, nc="00000001", cnonce=None, method="REGISTER", uri=None):
        """Calculate SIP digest auth response for different methods"""
        username = self.sip_config['login']
        password = self.sip_config['password']
        realm = self.auth_realm
        
        # Use provided URI or default to REGISTER URI
        if uri is None:
            uri = f"sip:{self.sip_config['sip_server']}"
        
        if cnonce is None:
            cnonce = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        
        # HA1 = MD5(username:realm:password)
        ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
        
        # HA2 = MD5(method:uri)
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        
        if qop == "auth":
            # Response = MD5(HA1:nonce:nc:cnonce:qop:HA2)
            response = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
        else:
            # Response = MD5(HA1:nonce:HA2)
            response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        
        return response, cnonce
    
    def _build_auth_header(self) -> str:
        """Build Authorization header for digest authentication"""
        username = self.sip_config['login']
        realm = self.auth_realm
        nonce = self.auth_nonce
        uri = f"sip:{self.sip_config['sip_server']}"
        
        # Calculate response using the working algorithm
        response, cnonce = self._calculate_sip_response(
            nonce=nonce,
            qop=self.auth_qop,
            method="REGISTER",
            uri=uri
        )
        
        self.logger.debug(f"Calculated response: {response}")
        
        # Build Authorization header according to RFC 2617
        auth_parts = [
            f'Authorization: Digest username="{username}"',
            f'realm="{realm}"',
            f'nonce="{nonce}"',
            f'uri="{uri}"',
            f'response="{response}"'
        ]
        
        # Add mandatory parameters for qop=auth
        if self.auth_qop:
            auth_parts.extend([
                f'qop={self.auth_qop}',
                f'nc=00000001',
                f'cnonce="{cnonce}"'
            ])
        
        if self.auth_opaque:
            auth_parts.append(f'opaque="{self.auth_opaque}"')
        
        # Always include algorithm
        auth_parts.append('algorithm=MD5')
        
        return ", ".join(auth_parts)
    
    def _parse_www_authenticate(self, header: str) -> Dict:
        """Parse WWW-Authenticate header"""
        params = {}
        try:
            # Extract parameters from header
            realm_match = re.search(r'realm="([^"]+)"', header)
            nonce_match = re.search(r'nonce="([^"]+)"', header)
            opaque_match = re.search(r'opaque="([^"]+)"', header)
            qop_match = re.search(r'qop="([^"]+)"', header)
            algorithm_match = re.search(r'algorithm=([^,]+)', header)
            stale_match = re.search(r'stale=([^,]+)', header)
            
            if realm_match:
                params['realm'] = realm_match.group(1)
            if nonce_match:
                params['nonce'] = nonce_match.group(1)
            if opaque_match:
                params['opaque'] = opaque_match.group(1)
            if qop_match:
                params['qop'] = qop_match.group(1)
            if algorithm_match:
                params['algorithm'] = algorithm_match.group(1)
            if stale_match:
                params['stale'] = stale_match.group(1).lower() == "true"
                
        except Exception as e:
            self.logger.error(f"Ошибка парсинга WWW-Authenticate: {e}")
        
        return params
    
    def _receiving_loop(self):
        """Receive SIP messages and put them in queue"""
        while self.running:
            try:
                if self.sip_socket:
                    # Check for incoming data
                    ready, _, _ = select.select([self.sip_socket], [], [], 0.5)
                    if ready:
                        data, addr = self.sip_socket.recvfrom(4096)
                        message = data.decode('utf-8', errors='ignore')
                        
                        # Log detailed message info
                        self._log_incoming_message(message, addr)
                        
                        # Put message in queue for processing
                        self.message_queue.put(('message', message, addr))
                        self.messages_received += 1
                
                time.sleep(0.01)
                
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"Ошибка в receiving loop: {e}")
    
    def _log_incoming_message(self, message: str, addr: tuple):
        """Log detailed information about incoming SIP message"""
        try:
            lines = message.split('\r\n')
            if not lines:
                return
                
            first_line = lines[0]
            
            # Determine message type
            if first_line.startswith('SIP/2.0'):
                # This is a response
                status_parts = first_line.split(' ')
                if len(status_parts) >= 3:
                    status_code = status_parts[1]
                    status_text = ' '.join(status_parts[2:])
                    
                    # Extract additional headers for debugging
                    via_header = next((line for line in lines if line.startswith('Via:')), 'N/A')
                    from_header = next((line for line in lines if line.startswith('From:')), 'N/A')
                    to_header = next((line for line in lines if line.startswith('To:')), 'N/A')
                    call_id_header = next((line for line in lines if line.startswith('Call-ID:')), 'N/A')
                    cseq_header = next((line for line in lines if line.startswith('CSeq:')), 'N/A')
                    
                    self.logger.debug(f"ВХОДЯЩИЙ ОТВЕТ от {addr}")
                    self.logger.debug(f"   Status: {status_code} {status_text}")
                    self.logger.debug(f"   Via: {via_header}")
                    self.logger.debug(f"   From: {from_header}")
                    self.logger.debug(f"   To: {to_header}")
                    self.logger.debug(f"   Call-ID: {call_id_header}")
                    self.logger.debug(f"   CSeq: {cseq_header}")
                    
                    # Log specific headers for different response types
                    if status_code == "401":
                        www_auth = next((line for line in lines if line.startswith('WWW-Authenticate:')), 'N/A')
                        self.logger.debug(f"   WWW-Authenticate: {www_auth}")
                    elif status_code == "200":
                        contact_header = next((line for line in lines if line.startswith('Contact:')), 'N/A')
                        expires_header = next((line for line in lines if line.startswith('Expires:')), 'N/A')
                        self.logger.debug(f"   Contact: {contact_header}")
                        self.logger.debug(f"   Expires: {expires_header}")
                    
            else:
                # This is a request
                request_parts = first_line.split(' ')
                if len(request_parts) >= 2:
                    method = request_parts[0]
                    
                    # Extract headers for debugging
                    via_header = next((line for line in lines if line.startswith('Via:')), 'N/A')
                    from_header = next((line for line in lines if line.startswith('From:')), 'N/A')
                    to_header = next((line for line in lines if line.startswith('To:')), 'N/A')
                    call_id_header = next((line for line in lines if line.startswith('Call-ID:')), 'N/A')
                    cseq_header = next((line for line in lines if line.startswith('CSeq:')), 'N/A')
                    contact_header = next((line for line in lines if line.startswith('Contact:')), 'N/A')
                    
                    self.logger.debug(f"ВХОДЯЩИЙ ЗАПРОС от {addr}")
                    self.logger.debug(f"   Method: {method}")
                    self.logger.debug(f"   Via: {via_header}")
                    self.logger.debug(f"   From: {from_header}")
                    self.logger.debug(f"   To: {to_header}")
                    self.logger.debug(f"   Call-ID: {call_id_header}")
                    self.logger.debug(f"   CSeq: {cseq_header}")
                    
                    if method == "INVITE":
                        # Log additional INVITE details
                        content_type = next((line for line in lines if line.startswith('Content-Type:')), 'N/A')
                        self.logger.debug(f"   Content-Type: {content_type}")
                    
                    # Log full message in debug mode for complex requests
                    if self.logger.isEnabledFor(logging.DEBUG) and method in ["INVITE", "OPTIONS"]:
                        self.logger.debug("   Полное сообщение:")
                        for line in lines[:20]:  # Log first 20 lines to avoid too much output
                            if line.strip():
                                self.logger.debug(f"      {line}")
                        
        except Exception as e:
            self.logger.error(f"Ошибка логирования входящего сообщения: {e}")
    
    def _processing_loop(self):
        """Process messages from queue in main thread context"""
        while self.running:
            try:
                # Process all available messages
                while not self.message_queue.empty():
                    msg_type, data, addr = self.message_queue.get_nowait()
                    
                    if msg_type == 'message':
                        self._handle_sip_message(data, addr)
                
                time.sleep(0.01)
                
            except Exception as e:
                if self.running:
                    self.logger.error(f"Ошибка в processing loop: {e}")
    
    def _handle_sip_message(self, message: str, addr: tuple):
        """Handle incoming SIP message"""
        try:
            self.logger.debug(f"Обработка сообщения от {addr}")
        
            # Parse first line to determine message type
            lines = message.split('\r\n')
            first_line = lines[0] if lines else ""
        
            if first_line.startswith('SIP/2.0'):
                # This is a response
                status_parts = first_line.split(' ')
                if len(status_parts) >= 2:
                    status_code = status_parts[1]
                    if status_code == "401":
                        self._handle_401_response(message)
                    elif status_code == "407":
                        self._handle_407_response(message)
                    elif status_code == "200":
                        self._handle_200_response(message)
                    elif status_code == "100":
                        self._handle_100_response(message)
                    elif status_code == "180":
                        self._handle_180_response(message)
                    elif status_code == "183":
                        self._handle_183_response(message)
                    elif status_code == "486":
                        self._handle_486_response(message)
                    elif status_code == "487":
                        self._handle_487_response(message)
                    elif status_code == "403":
                        self.logger.warning("Получен 403 Forbidden")
                    elif status_code == "404":
                        self.logger.warning("Получен 404 Not Found")
                    elif status_code == "480":
                        self.logger.warning("Получен 480 Temporarily Unavailable")
                    else:
                        self.logger.debug(f"Получен ответ: {status_code}")
        
            elif first_line.startswith('OPTIONS '):
                self._handle_options_request(message, addr)
            elif first_line.startswith('INVITE '):
                self._handle_invite_request(message)
            elif first_line.startswith('BYE '):
                self._handle_bye_request(message)
            elif first_line.startswith('CANCEL '):
                self._handle_cancel_request(message)
            elif first_line.startswith('MESSAGE '):
                self._handle_message_request(message, addr)
            elif first_line.startswith('NOTIFY '):
                self._handle_notify_request(message, addr)
            elif first_line.startswith('SUBSCRIBE '):
                self._handle_subscribe_request(message, addr)
            else:
                self.logger.debug(f"Необработанный тип сообщения: {first_line.split()[0] if first_line.split() else 'UNKNOWN'}")
                
        except Exception as e:
            self.logger.error(f"Ошибка обработки SIP сообщения: {e}")

    def _handle_100_response(self, message: str):
        """Handle 100 Trying response"""
        if self.call_state == "DIALING":
            self.logger.info("Получен 100 Trying - вызов обрабатывается")
    
    def _handle_180_response(self, message: str):
        """Handle 180 Ringing response"""
        if self.call_state == "DIALING":
            self.call_state = "RINGING"
            self.logger.info("Получен 180 Ringing - абонент звонит")
            
            # Notify WebSocket about ringing
            if self.websocket_bridge and self.main_event_loop:
                asyncio.run_coroutine_threadsafe(
                    self.websocket_bridge.notify_call_ringing(),
                    self.main_event_loop
                )
    
    def _handle_183_response(self, message: str):
        """Handle 183 Session Progress response"""
        if self.call_state == "DIALING":
            self.call_state = "RINGING"
            self.logger.info("Получен 183 Session Progress - вызов прогрессирует")
    
    def _handle_486_response(self, message: str):
        """Handle 486 Busy Here response"""
        self.logger.warning("Получен 486 Busy Here - абонент занят")
        if self.call_state in ["DIALING", "RINGING"]:
            if self.websocket_bridge and self.main_event_loop:
                asyncio.run_coroutine_threadsafe(
                    self.websocket_bridge.notify_call_failed("Абонент занят"),
                    self.main_event_loop
                )
            self._reset_call_state()
    
    def _handle_487_response(self, message: str):
        """Handle 487 Request Terminated response"""
        self.logger.info("Получен 487 Request Terminated - запрос отменен")
        self._reset_call_state()

    def _handle_401_response(self, message: str):
        """Handle 401 Unauthorized response"""
        self.logger.info("Получен 401 Unauthorized - требуется аутентификация")
        
        # Parse WWW-Authenticate header
        auth_match = re.search(r'WWW-Authenticate:\s*(Digest[^\r\n]+)', message)
        if auth_match:
            auth_header = auth_match.group(1)
            auth_params = self._parse_www_authenticate(auth_header)
            
            self.logger.info(f"Параметры аутентификации: {auth_params}")
            
            # Store auth parameters and save to cache
            self.auth_realm = auth_params.get('realm')
            self.auth_nonce = auth_params.get('nonce')
            self.auth_opaque = auth_params.get('opaque')
            self.auth_qop = auth_params.get('qop')
            
            # Save to cache for future use
            self.save_auth_cache()
            
            # Increment CSeq for authenticated request
            self.cseq_counter += 1
            
            # Send authenticated register
            self._send_register_sync(with_auth=True)
        else:
            self.logger.error("WWW-Authenticate header не найден в 401 ответе")

    def _handle_407_response(self, message: str):
        """Handle 407 Proxy Authentication Required response for INVITE"""
        self.logger.info("Получен 407 Proxy Authentication Required - требуется аутентификация для INVITE")
        
        # Parse Proxy-Authenticate header
        auth_match = re.search(r'Proxy-Authenticate:\s*(Digest[^\r\n]+)', message)
        if auth_match:
            auth_header = auth_match.group(1)
            auth_params = self._parse_www_authenticate(auth_header)
            
            self.logger.info(f"Параметры proxy аутентификации: {auth_params}")
            
            # Store auth parameters and save to cache
            self.auth_realm = auth_params.get('realm')
            self.auth_nonce = auth_params.get('nonce')
            self.auth_opaque = auth_params.get('opaque')
            self.auth_qop = auth_params.get('qop')
            
            # Save to cache for future use
            self.save_auth_cache()
            
            # Increment CSeq for authenticated INVITE
            self.cseq_counter += 1
            
            # Resend INVITE with authentication
            self._resend_invite_with_auth()
        else:
            self.logger.error("Proxy-Authenticate header не найден в 407 ответе")

    def _resend_invite_with_auth(self):
        """Resend INVITE with authentication headers"""
        try:
            server = self.sip_config['sip_server']
            port = self.sip_config['sip_port']
            
            invite_msg = self._build_invite_message(self.dialed_number)
            
            self.logger.debug(f"Повторная отправка INVITE с аутентификацией:\n{invite_msg}")
            
            self.sip_socket.sendto(invite_msg.encode(), (server, port))
            self.messages_sent += 1
            self.logger.info("INVITE с аутентификацией отправлен")
            
        except Exception as e:
            self.logger.error(f"Ошибка повторной отправки INVITE: {e}")
            if self.websocket_bridge and self.main_event_loop:
                asyncio.run_coroutine_threadsafe(
                    self.websocket_bridge.notify_call_failed(f"Ошибка аутентификации: {e}"),
                    self.main_event_loop
                )
    
    def _send_register_sync(self, with_auth: bool):
        """Send REGISTER synchronously (from processing thread)"""
        try:
            server = self.sip_config['sip_server']
            port = self.sip_config['sip_port']
            
            register_msg = self._build_register_message(with_auth=with_auth)
            
            self.logger.debug(f"Отправка REGISTER:\n{register_msg}")
            
            self.sip_socket.sendto(register_msg.encode(), (server, port))
            self.messages_sent += 1
            
            if with_auth:
                self.logger.info("Аутентифицированный REGISTER отправлен")
            else:
                self.logger.info("REGISTER отправлен")
            
        except Exception as e:
            self.logger.error(f"Ошибка отправки REGISTER: {e}")
    
    def _handle_200_response(self, message: str):
        """Handle 200 OK response"""
        # Check if this is a response to OPTIONS
        if "OPTIONS" in message:
            self._handle_options_response(message)
            return
            
        # Check if this is a response to INVITE (call established)
        if "INVITE" in message and self.call_state in ["DIALING", "RINGING"]:
            self._handle_invite_200_response(message)
            return
            
        # Handle REGISTER 200 OK
        self.registered = True
        self.last_register_time = time.time()
        self.logger.info("Получен 200 OK - успешная регистрация")
        
        # Extract expiration time
        expires_match = re.search(r'Expires:\s*(\d+)', message)
        if expires_match:
            self.register_expires = int(expires_match.group(1))
            self.logger.debug(f"Время жизни регистрации: {self.register_expires} секунд")
        
        # Schedule WebSocket notification in main thread
        if self.websocket_bridge and self.main_event_loop:
            asyncio.run_coroutine_threadsafe(
                self.websocket_bridge.notify_sip_registered(),
                self.main_event_loop
            )
    
    def _handle_invite_200_response(self, message: str):
        """Handle 200 OK response to INVITE (call answered)"""
        self.call_state = "ACTIVE"
        self.active_call = True
        self.logger.info("Получен 200 OK - звонок установлен")
        
        # Extract To tag
        to_match = re.search(r'To:[^;]*;tag=([^\s\r\n]+)', message)
        if to_match:
            self.to_tag = to_match.group(1)
        
        # Send ACK
        self._send_ack_sync()
        
        # Notify WebSocket about call answered
        if self.websocket_bridge and self.main_event_loop:
            asyncio.run_coroutine_threadsafe(
                self.websocket_bridge.notify_call_answered(),
                self.main_event_loop
            )
    
    def _send_ack_sync(self):
        """Send ACK for established call"""
        try:
            server = self.sip_config['sip_server']
            port = self.sip_config['sip_port']
            local_ip = self._get_local_ip()
            login = self.sip_config['login']
            
            ack_msg = [
                f"ACK sip:{self.dialed_number}@{server} SIP/2.0",
                f"Via: SIP/2.0/UDP {local_ip}:5060;branch=z9hG4bK{random.getrandbits(32)};rport",
                "Max-Forwards: 70",
                f"From: <sip:{self.sip_config['number']}@{server}>;tag={self.from_tag}",
                f"To: <sip:{self.dialed_number}@{server}>;tag={self.to_tag}",
                f"Call-ID: {self.current_call_id}",
                f"CSeq: {self.cseq_counter} ACK",
                f"Contact: <sip:{login}@{local_ip}:5060;transport=udp>",
                "User-Agent: SIPGateway/1.0",
                "Content-Length: 0",
                "",
                ""
            ]
            
            ack_msg_str = "\r\n".join(ack_msg)
            self.sip_socket.sendto(ack_msg_str.encode(), (server, port))
            self.messages_sent += 1
            self.logger.debug("ACK отправлен")
            
        except Exception as e:
            self.logger.error(f"Ошибка отправки ACK: {e}")
    
    def _handle_options_response(self, message: str):
        """Handle 200 OK response to OPTIONS request"""
        self.last_options_response = time.time()
        self.logger.debug("Получен 200 OK на OPTIONS запрос - сервер доступен")
        
        # Extract server capabilities if available
        lines = message.split('\r\n')
        allow_header = next((line for line in lines if line.startswith('Allow:')), '')
        supported_header = next((line for line in lines if line.startswith('Supported:')), '')
        
        if allow_header:
            self.logger.debug(f"   Сервер поддерживает: {allow_header}")
        if supported_header:
            self.logger.debug(f"   Расширения сервера: {supported_header}")
    
    def _handle_options_request(self, message: str, addr: tuple):
        """Handle OPTIONS request (keep-alive from server)"""
        try:
            self.logger.debug("Получен OPTIONS запрос (keep-alive от сервера)")
            
            # Parse headers from OPTIONS request
            lines = message.split('\r\n')
            via_header = next((line for line in lines if line.startswith('Via:')), '')
            from_header = next((line for line in lines if line.startswith('From:')), '')
            to_header = next((line for line in lines if line.startswith('To:')), '')
            call_id_header = next((line for line in lines if line.startswith('Call-ID:')), '')
            cseq_header = next((line for line in lines if line.startswith('CSeq:')), '')
            
            # Extract from tag
            from_tag_match = re.search(r'tag=([^\s;]+)', from_header)
            from_tag = from_tag_match.group(1) if from_tag_match else ""
            
            # Build 200 OK response
            local_ip = self._get_local_ip()
            response = [
                "SIP/2.0 200 OK",
                via_header,
                from_header,
                to_header + (f";tag={self._generate_tag()}" if not from_tag else ""),
                call_id_header,
                cseq_header,
                f"Contact: <sip:{self.sip_config['login']}@{local_ip}:5060;transport=udp>",
                "User-Agent: SIPGateway/1.0",
                "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, SUBSCRIBE, NOTIFY, MESSAGE, INFO",
                "Supported: replaces, timer, outbound, path, gruu",
                "Accept: application/sdp, application/dtmf-relay",
                "Accept-Encoding: identity",
                "Accept-Language: en, ru",
                "Content-Length: 0",
                "",
                ""
            ]
            
            response_msg = "\r\n".join(response)
            
            # Send response
            self.sip_socket.sendto(response_msg.encode(), addr)
            self.messages_sent += 1
            self.logger.debug("Отправлен 200 OK на OPTIONS запрос от сервера")
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки OPTIONS: {e}")
    
    def _handle_message_request(self, message: str, addr: tuple):
        """Handle MESSAGE request"""
        try:
            self.logger.debug("Получен MESSAGE запрос")
            
            # Parse headers
            lines = message.split('\r\n')
            via_header = next((line for line in lines if line.startswith('Via:')), '')
            from_header = next((line for line in lines if line.startswith('From:')), '')
            to_header = next((line for line in lines if line.startswith('To:')), '')
            call_id_header = next((line for line in lines if line.startswith('Call-ID:')), '')
            cseq_header = next((line for line in lines if line.startswith('CSeq:')), '')
            
            # Send 200 OK response
            response = [
                "SIP/2.0 200 OK",
                via_header,
                from_header,
                to_header,
                call_id_header,
                cseq_header,
                "Content-Length: 0",
                "",
                ""
            ]
            
            response_msg = "\r\n".join(response)
            self.sip_socket.sendto(response_msg.encode(), addr)
            self.messages_sent += 1
            self.logger.debug("Отправлен 200 OK на MESSAGE запрос")
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки MESSAGE: {e}")
    
    def _handle_notify_request(self, message: str, addr: tuple):
        """Handle NOTIFY request"""
        try:
            self.logger.debug("Получен NOTIFY запрос")
            
            # Send 200 OK response
            lines = message.split('\r\n')
            via_header = next((line for line in lines if line.startswith('Via:')), '')
            from_header = next((line for line in lines if line.startswith('From:')), '')
            to_header = next((line for line in lines if line.startswith('To:')), '')
            call_id_header = next((line for line in lines if line.startswith('Call-ID:')), '')
            cseq_header = next((line for line in lines if line.startswith('CSeq:')), '')
            
            response = [
                "SIP/2.0 200 OK",
                via_header,
                from_header,
                to_header,
                call_id_header,
                cseq_header,
                "Content-Length: 0",
                "",
                ""
            ]
            
            response_msg = "\r\n".join(response)
            self.sip_socket.sendto(response_msg.encode(), addr)
            self.messages_sent += 1
            self.logger.debug("Отправлен 200 OK на NOTIFY запрос")
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки NOTIFY: {e}")
    
    def _handle_subscribe_request(self, message: str, addr: tuple):
        """Handle SUBSCRIBE request"""
        try:
            self.logger.debug("Получен SUBSCRIBE запрос")
            
            # Send 200 OK response
            lines = message.split('\r\n')
            via_header = next((line for line in lines if line.startswith('Via:')), '')
            from_header = next((line for line in lines if line.startswith('From:')), '')
            to_header = next((line for line in lines if line.startswith('To:')), '')
            call_id_header = next((line for line in lines if line.startswith('Call-ID:')), '')
            cseq_header = next((line for line in lines if line.startswith('CSeq:')), '')
            
            response = [
                "SIP/2.0 200 OK",
                via_header,
                from_header,
                to_header,
                call_id_header,
                cseq_header,
                "Content-Length: 0",
                "",
                ""
            ]
            
            response_msg = "\r\n".join(response)
            self.sip_socket.sendto(response_msg.encode(), addr)
            self.messages_sent += 1
            self.logger.debug("Отправлен 200 OK на SUBSCRIBE запрос")
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки SUBSCRIBE: {e}")
    
    def _handle_cancel_request(self, message: str):
        """Handle CANCEL request"""
        self.logger.info("Получен CANCEL запрос - отмена звонка")
        
        # Schedule cleanup in main thread
        if self.main_event_loop:
            asyncio.run_coroutine_threadsafe(
                self._cleanup_call(),
                self.main_event_loop
            )
    
    def _handle_invite_request(self, message: str):
        """Handle INVITE request"""
        try:
            # Extract caller information
            from_match = re.search(r'From:[^<]*<sip:([^@]+)@', message)
            call_id_match = re.search(r'Call-ID:\s*([^\r\n]+)', message)
            
            if from_match:
                self.caller_number = from_match.group(1)
            if call_id_match:
                self.current_call_id = call_id_match.group(1).strip()
            
            self.incoming_call = True
            self.logger.info(f"Входящий звонок от: {self.caller_number}")
            
            # Schedule WebSocket notification in main thread
            if self.websocket_bridge and self.main_event_loop:
                asyncio.run_coroutine_threadsafe(
                    self.websocket_bridge.notify_incoming_call(self.caller_number),
                    self.main_event_loop
                )
                
        except Exception as e:
            self.logger.error(f"Ошибка обработки INVITE: {e}")
    
    def _handle_bye_request(self, message: str):
        """Handle BYE request"""
        self.logger.info("Получен BYE - завершение звонка")
        
        # Schedule cleanup in main thread
        if self.main_event_loop:
            asyncio.run_coroutine_threadsafe(
                self._cleanup_call(),
                self.main_event_loop
            )
    
    def _keepalive_loop(self):
        """Send periodic re-registration and handle keep-alive"""
        while self.running:
            try:
                # Re-register if needed (every 20 minutes or when expired)
                if self.registered and time.time() - self.last_register_time > 240:  # 4 minutes
                    self.logger.info("Периодическая перерегистрация")
                    self.cseq_counter += 1
                    self._send_register_sync(with_auth=True)
                    self.last_register_time = time.time()
                
                # Send OPTIONS keep-alive if no server OPTIONS received recently
                if self.registered and time.time() - self.last_options_response > 60:  # 1 minute
                    # Use synchronous method instead of async in thread
                    self._send_options_sync()
                    self.last_options_response = time.time()
                
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                if self.running:
                    self.logger.error(f"Ошибка в keepalive loop: {e}")
    
    async def answer_call(self) -> bool:
        """Answer incoming call"""
        try:
            if not self.incoming_call:
                self.logger.error("Нет входящего звонка для ответа")
                return False
                
            # Здесь будет реализация ответа на вызов
            self.logger.info("Ответ на входящий звонок")
            self.incoming_call = False
            self.active_call = True
            self.call_state = "ACTIVE"
            
            if self.websocket_bridge:
                await self.websocket_bridge.notify_call_answered()
                
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка ответа на звонок: {e}")
            return False

    async def hangup_call(self) -> bool:
        """Hang up current call"""
        try:
            if not self.active_call and not self.incoming_call and self.call_state == "IDLE":
                self.logger.error("Нет активного звонка для завершения")
                return False
                
            self.logger.info("Завершение звонка")
            
            # Send BYE if we have an active call
            if self.active_call and self.current_call_id:
                self._send_bye_sync()
            
            await self._cleanup_call()
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка завершения звонка: {e}")
            return False

    def _send_bye_sync(self):
        """Send BYE message to hang up call"""
        try:
            server = self.sip_config['sip_server']
            port = self.sip_config['sip_port']
            local_ip = self._get_local_ip()
            login = self.sip_config['login']
            
            bye_msg = [
                f"BYE sip:{self.dialed_number}@{server} SIP/2.0",
                f"Via: SIP/2.0/UDP {local_ip}:5060;branch=z9hG4bK{random.getrandbits(32)};rport",
                "Max-Forwards: 70",
                f"From: <sip:{self.sip_config['number']}@{server}>;tag={self.from_tag}",
                f"To: <sip:{self.dialed_number}@{server}>;tag={self.to_tag}",
                f"Call-ID: {self.current_call_id}",
                f"CSeq: {self.cseq_counter + 1} BYE",
                f"Contact: <sip:{login}@{local_ip}:5060;transport=udp>",
                "User-Agent: SIPGateway/1.0",
                "Content-Length: 0",
                "",
                ""
            ]
            
            bye_msg_str = "\r\n".join(bye_msg)
            self.sip_socket.sendto(bye_msg_str.encode(), (server, port))
            self.messages_sent += 1
            self.logger.debug("BYE отправлен")
            
        except Exception as e:
            self.logger.error(f"Ошибка отправки BYE: {e}")

    async def send_dtmf(self, digit: str) -> bool:
        """Send DTMF tone"""
        try:
            if not self.active_call:
                self.logger.error("Нет активного звонка для отправки DTMF")
                return False
                
            # Здесь будет реализация отправки DTMF
            self.logger.info(f"Отправка DTMF: {digit}")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка отправки DTMF: {e}")
            return False

    async def _cleanup_call(self):
        """Clean up call state"""
        self.active_call = False
        self.incoming_call = False
        self.caller_number = ""
        self.dialed_number = ""
        self.current_call_id = None
        self.to_tag = None
        self.call_state = "IDLE"
        
        if self.websocket_bridge:
            await self.websocket_bridge.notify_call_ended()

    def _reset_call_state(self):
        """Reset call state without sending BYE"""
        self.active_call = False
        self.incoming_call = False
        self.caller_number = ""
        self.dialed_number = ""
        self.current_call_id = None
        self.to_tag = None
        self.call_state = "IDLE"

    def _generate_call_id(self) -> str:
        """Generate unique Call-ID"""
        return f"{random.getrandbits(32)}@{self._get_local_ip()}"

    def _generate_tag(self) -> str:
        """Generate unique tag"""
        return f"{random.getrandbits(32)}"

    def _get_local_ip(self) -> str:
        """Get local IP address"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except:
            return "127.0.0.1"

    async def disconnect(self):
        """Disconnect from SIP server"""
        try:
            self.running = False
            
            if self.active_call or self.incoming_call:
                await self.hangup_call()
            
            # Send unregister
            if self.registered and self.sip_socket:
                self.cseq_counter += 1
                unregister_msg = self._build_register_message(with_auth=True)
                unregister_msg = unregister_msg.replace("Expires: 3600", "Expires: 0")
                self.sip_socket.sendto(unregister_msg.encode(), 
                                    (self.sip_config['sip_server'], self.sip_config['sip_port']))
                self.messages_sent += 1
                self.logger.info("UNREGISTER отправлен")
            
            if self.sip_socket:
                self.sip_socket.close()
                self.sip_socket = None
            
            self.registered = False
            
            # Clear auth cache on disconnect
            self.clear_auth_cache()
            
            # Log statistics
            self.logger.info(f"Статистика: отправлено {self.messages_sent} сообщений, получено {self.messages_received} сообщений")
            self.logger.info("Отключение от SIP сервера завершено")
            
            # Notify WebSocket bridge about unregistration
            if self.websocket_bridge:
                await self.websocket_bridge.notify_sip_unregistered()
                
        except Exception as e:
            self.logger.error(f"Ошибка отключения: {e}")

    @property
    def is_registered(self) -> bool:
        """Check if client is registered"""
        return self.registered

    @property
    def is_in_call(self) -> bool:
        """Check if client is in active call"""
        return self.active_call

    def get_status(self) -> Dict:
        """Get client status"""
        return {
            'registered': self.registered,
            'in_call': self.active_call,
            'has_incoming': self.incoming_call,
            'caller_number': self.caller_number,
            'dialed_number': self.dialed_number,
            'call_id': self.current_call_id,
            'call_state': self.call_state,
            'sip_server': self.sip_config.get('sip_server', ''),
            'number': self.sip_config.get('number', ''),
            'messages_sent': self.messages_sent,
            'messages_received': self.messages_received,
            'last_options_response': self.last_options_response,
            'has_cached_auth': self.has_cached_auth()
        }