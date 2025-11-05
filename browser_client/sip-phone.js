class SIPPhone {
    constructor() {
        this.websocket = null;
        this.isConnected = false;
        this.isRegistered = false;
        this.isInCall = false;
        this.hasIncomingCall = false;
        this.callStartTime = null;
        this.callTimer = null;
        this.currentCaller = "";
        this.currentCallState = "IDLE";
        
        this.initializeElements();
        this.initializeEventListeners();
        this.connectWebSocket();
        this.log('SIP телефон инициализирован', 'info');
    }

    initializeElements() {
        // Статусные элементы
        this.connectionStatus = document.getElementById('connectionStatus');
        this.sipStatus = document.getElementById('sipStatus');
        
        // Информация о звонке
        this.remoteNumber = document.getElementById('remoteNumber');
        this.callDuration = document.getElementById('callDuration');
        this.callStatus = document.getElementById('callStatus');
        this.callInfo = document.getElementById('callInfo');
        
        // Кнопки управления
        this.answerBtn = document.getElementById('answerBtn');
        this.hangupBtn = document.getElementById('hangupBtn');
        this.dialBtn = document.getElementById('dialBtn');
        this.registerBtn = document.getElementById('registerBtn');
        this.unregisterBtn = document.getElementById('unregisterBtn');
        
        // Клавиатура и ввод
        this.phoneNumber = document.getElementById('phoneNumber');
        this.dtmfButtons = document.querySelectorAll('.dtmf-btn');
        
        // Настройки
        this.sipServer = document.getElementById('sipServer');
        this.sipPort = document.getElementById('sipPort');
        this.sipLogin = document.getElementById('sipLogin');
        this.sipPassword = document.getElementById('sipPassword');
        this.sipNumber = document.getElementById('sipNumber');
        this.logLevelSelect = document.getElementById('logLevel');
        this.clearLogsBtn = document.getElementById('clearLogs');
        
        // Логи
        this.logContainer = document.getElementById('logContainer');
    }

    initializeEventListeners() {
        // Кнопки управления звонком
        this.answerBtn.addEventListener('click', () => this.answerCall());
        this.hangupBtn.addEventListener('click', () => this.hangupCall());
        this.dialBtn.addEventListener('click', () => this.makeCall());
        this.registerBtn.addEventListener('click', () => this.registerSIP());
        this.unregisterBtn.addEventListener('click', () => this.unregisterSIP());

        // Клавиатура DTMF
        this.dtmfButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const digit = e.target.getAttribute('data-digit');
                this.sendDTMF(digit);
            });
        });

        // Ввод номера по Enter
        this.phoneNumber.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.makeCall();
            }
        });

        // Управление логированием
        this.logLevelSelect.addEventListener('change', () => this.changeLogLevel());
        this.clearLogsBtn.addEventListener('click', () => this.clearLogs());

        // Загрузка сохраненных настроек
        this.loadSettings();
    }

    connectWebSocket() {
        try {
            const wsUrl = `ws://localhost:8765`;
            this.websocket = new WebSocket(wsUrl);
            
            this.websocket.onopen = () => {
                this.log('WebSocket подключен', 'info');
                this.isConnected = true;
                this.updateConnectionStatus();
                this.requestStatus();
            };
            
            this.websocket.onmessage = (event) => {
                this.handleWebSocketMessage(event.data);
            };
            
            this.websocket.onclose = () => {
                this.log('WebSocket отключен', 'warning');
                this.isConnected = false;
                this.updateConnectionStatus();
                
                // Попытка переподключения через 5 секунд
                setTimeout(() => this.connectWebSocket(), 5000);
            };
            
            this.websocket.onerror = (error) => {
                this.log(`WebSocket ошибка: ${error}`, 'error');
            };
            
        } catch (error) {
            this.log(`Ошибка подключения WebSocket: ${error}`, 'error');
        }
    }

    handleWebSocketMessage(message) {
        try {
            const data = JSON.parse(message);
            this.log(`Получено: ${data.type}`, 'debug');
            
            switch (data.type) {
                case 'status_update':
                    this.handleStatusUpdate(data.payload);
                    break;
                case 'sip_registered':
                    this.handleSIPRegistered(data.payload);
                    break;
                case 'sip_unregistered':
                    this.handleSIPUnregistered(data.payload);
                    break;
                case 'incoming_call':
                    this.handleIncomingCall(data.payload);
                    break;
                case 'call_ringing':
                    this.handleCallRinging(data.payload);
                    break;
                case 'call_answered':
                    this.handleCallAnswered(data.payload);
                    break;
                case 'call_ended':
                    this.handleCallEnded(data.payload);
                    break;
                case 'call_failed':
                    this.handleCallFailed(data.payload);
                    break;
                case 'success':
                    this.log(`Успех: ${data.payload.message}`, 'info');
                    break;
                case 'error':
                    this.log(`Ошибка: ${data.payload.message}`, 'error');
                    break;
                default:
                    this.log(`Неизвестный тип сообщения: ${data.type}`, 'warning');
            }
        } catch (error) {
            this.log(`Ошибка обработки сообщения: ${error}`, 'error');
        }
    }

    handleStatusUpdate(payload) {
        this.isRegistered = payload.sip_registered;
        this.isInCall = payload.active_call;
        this.hasIncomingCall = payload.has_incoming;
        this.currentCaller = payload.caller_number;
        this.updateSIPStatus();
        this.updateCallControls();
        this.updateCallInfo();
    }

    handleSIPRegistered(payload) {
        this.isRegistered = true;
        this.log('Успешная регистрация на SIP сервере', 'info');
        this.updateSIPStatus();
        this.saveSettings();
    }

    handleSIPUnregistered(payload) {
        this.isRegistered = false;
        this.log('Регистрация SIP сброшена', 'warning');
        this.updateSIPStatus();
    }

    handleIncomingCall(payload) {
        this.hasIncomingCall = true;
        this.currentCaller = payload.caller_number;
        this.showIncomingCall(payload.caller_number);
    }

    handleCallRinging(payload) {
        this.callStatus.textContent = 'Абонент звонит...';
        this.log('Абонент звонит', 'info');
    }

    handleCallAnswered(payload) {
        this.isInCall = true;
        this.hasIncomingCall = false;
        this.stopRingtone(); // Останавливаем звук звонка при ответе
        this.startCallTimer();
        this.log('Звонок установлен', 'info');
        this.updateCallControls();
        this.updateCallInfo();
    }

    handleCallEnded(payload) {
        this.isInCall = false;
        this.hasIncomingCall = false;
        this.stopCallTimer();
        this.stopRingtone(); // Явно останавливаем звук звонка
        this.hideCallInfo();
        this.log('Звонок завершен', 'info');
        this.updateCallControls();
    }

    handleCallFailed(payload) {
        this.log(`Ошибка звонка: ${payload.reason}`, 'error');
        this.stopRingtone(); // Останавливаем звук звонка при ошибке
        this.hideCallInfo();
        this.updateCallControls();
    }

    sendWebSocketMessage(message) {
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
            this.websocket.send(JSON.stringify(message));
        } else {
            this.log('WebSocket не подключен', 'error');
        }
    }

    requestStatus() {
        this.sendWebSocketMessage({
            type: 'get_status',
            payload: {}
        });
    }

    async registerSIP() {
        const settings = this.getSIPSettings();
        
        if (!this.validateSIPSettings(settings)) {
            this.log('Заполните все настройки SIP', 'warning');
            return;
        }

        this.sendWebSocketMessage({
            type: 'sip_register',
            payload: settings
        });
        
        this.log('Отправлен запрос регистрации SIP', 'info');
    }

    async unregisterSIP() {
        this.sendWebSocketMessage({
            type: 'sip_unregister',
            payload: {}
        });
        
        this.log('Отправлен запрос отключения SIP', 'info');
    }

    async makeCall() {
        const number = this.phoneNumber.value.trim();
        if (!number) {
            this.log('Введите номер для вызова', 'warning');
            return;
        }

        this.sendWebSocketMessage({
            type: 'sip_make_call',
            payload: { number: number }
        });
        
        this.showOutgoingCall(number);
        this.log(`Набор номера: ${number}`, 'info');
    }

    async answerCall() {
        this.sendWebSocketMessage({
            type: 'sip_answer_call',
            payload: {}
        });
        
        this.log('Принятие входящего звонка', 'info');
    }

    async hangupCall() {
        // Сначала отправляем сигнал завершения на сервер
        this.sendWebSocketMessage({
            type: 'sip_hangup_call',
            payload: {}
        });
        
        // Сразу обновляем локальное состояние
        this.isInCall = false;
        this.hasIncomingCall = false;
        this.stopRingtone();
        this.stopCallTimer();
        this.updateCallControls();
        
        this.log('Отправлен сигнал завершения звонка', 'info');
    }

    async sendDTMF(digit) {
        if (this.isInCall) {
            this.sendWebSocketMessage({
                type: 'sip_send_dtmf',
                payload: { digit: digit }
            });
            
            this.log(`Отправлен DTMF: ${digit}`, 'info');
        } else {
            this.log('Нет активного звонка для отправки DTMF', 'warning');
        }
    }

    async sendMessage(toNumber, content) {
        if (!this.isRegistered) {
            this.log('Не зарегистрирован для отправки сообщений', 'warning');
            return false;
        }

        this.sendWebSocketMessage({
            type: 'sip_send_message',
            payload: {
                to_number: toNumber,
                content: content
            }
        });
        
        this.log(`Отправка сообщения на номер: ${toNumber}`, 'info');
        return true;
    }

    async changeLogLevel() {
        const logLevel = this.logLevelSelect.value;
        
        try {
            const response = await fetch(`http://localhost:8000/api/logging/level`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    level: logLevel
                })
            });
            
            if (response.ok) {
                this.log(`Уровень логирования изменен на: ${logLevel}`, 'info');
                this.saveSettings();
            } else {
                this.log('Ошибка изменения уровня логирования', 'error');
            }
        } catch (error) {
            this.log(`Ошибка изменения уровня логирования: ${error}`, 'error');
        }
    }

    async clearLogs() {
        try {
            const response = await fetch(`http://localhost:8000/api/logs`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                this.log('Логи очищены', 'info');
                this.logContainer.innerHTML = '';
            } else {
                this.log('Ошибка очистки логов', 'error');
            }
        } catch (error) {
            this.log(`Ошибка очистки логов: ${error}`, 'error');
        }
    }

    // Вспомогательные методы
    validateSIPSettings(settings) {
        return settings.sip_server && settings.sip_port && 
               settings.login && settings.password && settings.number;
    }

    getSIPSettings() {
        return {
            sip_server: this.sipServer.value.trim(),
            sip_port: parseInt(this.sipPort.value) || 5060,
            login: this.sipLogin.value.trim(),
            password: this.sipPassword.value.trim(),
            number: this.sipNumber.value.trim()
        };
    }

    showIncomingCall(callerNumber) {
        this.callInfo.style.display = 'block';
        this.callInfo.className = 'call-info incoming';
        this.remoteNumber.textContent = callerNumber;
        this.callStatus.textContent = 'Входящий вызов...';
        this.answerBtn.disabled = false;
        this.hangupBtn.disabled = false;
        
        // Воспроизведение звука входящего вызова
        this.playRingtone();
    }

    showOutgoingCall(number) {
        this.callInfo.style.display = 'block';
        this.callInfo.className = 'call-info';
        this.remoteNumber.textContent = number;
        this.callStatus.textContent = 'Установка соединения...';
        this.answerBtn.disabled = true;
        this.hangupBtn.disabled = false;
    }

    updateCallInfo() {
        if (this.isInCall) {
            this.callInfo.style.display = 'block';
            this.callInfo.className = 'call-info';
            this.remoteNumber.textContent = this.currentCaller || this.phoneNumber.value;
            this.callStatus.textContent = 'Разговор...';
        } else if (this.hasIncomingCall) {
            this.showIncomingCall(this.currentCaller);
        }
    }

    hideCallInfo() {
        this.callInfo.style.display = 'none';
        this.remoteNumber.textContent = '';
        this.callDuration.textContent = '';
        this.callStatus.textContent = '';
        this.stopRingtone();
    }

    playRingtone() {
        // Создаем простой рингтон с Web Audio API
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            
            this.ringtoneInterval = setInterval(() => {
                const oscillator = audioContext.createOscillator();
                const gainNode = audioContext.createGain();
                
                oscillator.connect(gainNode);
                gainNode.connect(audioContext.destination);
                
                oscillator.frequency.value = 440;
                oscillator.type = 'sine';
                
                gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
                gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);
                
                oscillator.start(audioContext.currentTime);
                oscillator.stop(audioContext.currentTime + 0.5);
            }, 2000);
            
        } catch (error) {
            console.log('Не удалось воспроизвести рингтон:', error);
        }
    }

    stopRingtone() {
        if (this.ringtoneInterval) {
            clearInterval(this.ringtoneInterval);
            this.ringtoneInterval = null;
        }
    }

    startCallTimer() {
        this.callStartTime = new Date();
        this.callTimer = setInterval(() => {
            const now = new Date();
            const duration = Math.floor((now - this.callStartTime) / 1000);
            const minutes = Math.floor(duration / 60);
            const seconds = duration % 60;
            this.callDuration.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }, 1000);
    }

    stopCallTimer() {
        if (this.callTimer) {
            clearInterval(this.callTimer);
            this.callTimer = null;
        }
        this.callDuration.textContent = '';
    }

    updateConnectionStatus() {
        if (this.isConnected) {
            this.connectionStatus.textContent = 'Подключен';
            this.connectionStatus.className = 'status connected';
        } else {
            this.connectionStatus.textContent = 'Отключен';
            this.connectionStatus.className = 'status disconnected';
        }
    }

    updateSIPStatus() {
        if (this.isRegistered) {
            this.sipStatus.textContent = 'Зарегистрирован';
            this.sipStatus.className = 'sip-status registered';
            this.registerBtn.disabled = true;
            this.unregisterBtn.disabled = false;
            this.dialBtn.disabled = false;
        } else {
            this.sipStatus.textContent = 'Не зарегистрирован';
            this.sipStatus.className = 'sip-status unregistered';
            this.registerBtn.disabled = false;
            this.unregisterBtn.disabled = true;
            this.dialBtn.disabled = true;
        }
    }

    updateCallControls() {
        if (this.isInCall) {
            this.answerBtn.disabled = true;
            this.hangupBtn.disabled = false;
            this.dialBtn.disabled = true;
            this.phoneNumber.disabled = true;
        } else if (this.hasIncomingCall) {
            this.answerBtn.disabled = false;
            this.hangupBtn.disabled = false;
            this.dialBtn.disabled = true;
            this.phoneNumber.disabled = true;
        } else {
            this.answerBtn.disabled = true;
            this.hangupBtn.disabled = true;
            this.dialBtn.disabled = !this.isRegistered;
            this.phoneNumber.disabled = !this.isRegistered;
        }
    }

    log(message, level = 'info') {
        const timestamp = new Date().toLocaleTimeString();
        const logEntry = document.createElement('div');
        logEntry.className = `log-entry ${level}`;
        logEntry.textContent = `[${timestamp}] ${message}`;
        
        this.logContainer.appendChild(logEntry);
        this.logContainer.scrollTop = this.logContainer.scrollHeight;
        
        // Сохраняем логи в localStorage (максимум 1000 записей)
        this.saveLogToStorage(timestamp, message, level);
    }

    saveLogToStorage(timestamp, message, level) {
        try {
            let logs = JSON.parse(localStorage.getItem('sip_phone_logs') || '[]');
            logs.push({ timestamp, message, level });
            
            // Ограничиваем количество логов
            if (logs.length > 1000) {
                logs = logs.slice(-500);
            }
            
            localStorage.setItem('sip_phone_logs', JSON.stringify(logs));
        } catch (error) {
            console.error('Ошибка сохранения логов:', error);
        }
    }

    loadLogsFromStorage() {
        try {
            const logs = JSON.parse(localStorage.getItem('sip_phone_logs') || '[]');
            logs.forEach(log => {
                const logEntry = document.createElement('div');
                logEntry.className = `log-entry ${log.level}`;
                logEntry.textContent = `[${log.timestamp}] ${log.message}`;
                this.logContainer.appendChild(logEntry);
            });
            this.logContainer.scrollTop = this.logContainer.scrollHeight;
        } catch (error) {
            console.error('Ошибка загрузки логов:', error);
        }
    }

    saveSettings() {
        const settings = this.getSIPSettings();
        settings.log_level = this.logLevelSelect.value;
        localStorage.setItem('sip_settings', JSON.stringify(settings));
        this.log('Настройки сохранены', 'info');
    }

    loadSettings() {
        try {
            const saved = localStorage.getItem('sip_settings');
            if (saved) {
                const settings = JSON.parse(saved);
                this.sipServer.value = settings.sip_server || '';
                this.sipPort.value = settings.sip_port || '5060';
                this.sipLogin.value = settings.login || '';
                this.sipPassword.value = settings.password || '';
                this.sipNumber.value = settings.number || '';
                
                if (settings.log_level) {
                    this.logLevelSelect.value = settings.log_level;
                }
                
                this.log('Настройки загружены', 'info');
            }
            
            // Загружаем логи из localStorage
            this.loadLogsFromStorage();
            
        } catch (error) {
            this.log('Ошибка загрузки настроек', 'error');
        }
    }

    destroy() {
        if (this.websocket) {
            this.websocket.close();
        }
        this.stopCallTimer();
        this.stopRingtone();
        this.log('SIP телефон остановлен', 'info');
    }
}

// Глобальная инициализация
let sipPhone = null;

document.addEventListener('DOMContentLoaded', function() {
    sipPhone = new SIPPhone();
    window.sipPhone = sipPhone;
});

// Очистка при закрытии страницы
window.addEventListener('beforeunload', function() {
    if (sipPhone) {
        sipPhone.destroy();
    }
});