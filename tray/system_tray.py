import sys
import asyncio
import logging
import webbrowser
from pathlib import Path

try:
    from PyQt6.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QWidget, 
                                QVBoxLayout, QLabel, QPushButton, QMainWindow,
                                QTextEdit, QTabWidget, QFormLayout, QLineEdit,
                                QSpinBox, QComboBox, QCheckBox, QDialog, QMessageBox)
    from PyQt6.QtGui import QIcon, QPixmap, QAction, QPainter, QFont
    from PyQt6.QtCore import QTimer, Qt, QSize, pyqtSignal, QObject
    from PyQt6.QtNetwork import QLocalSocket, QLocalServer
except ImportError:
    from PySide6.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QWidget,
                                  QVBoxLayout, QLabel, QPushButton, QMainWindow,
                                  QTextEdit, QTabWidget, QFormLayout, QLineEdit,
                                  QSpinBox, QComboBox, QCheckBox, QDialog, QMessageBox)
    from PySide6.QtGui import QIcon, QPixmap, QAction, QPainter, QFont
    from PyQt6.QtCore import QTimer, Qt, QSize, Signal as pyqtSignal, QObject
    from PyQt6.QtNetwork import QLocalSocket, QLocalServer

class AsyncSignal(QObject):
    """Bridge for async signals"""
    show_phone_signal = pyqtSignal()
    show_settings_signal = pyqtSignal()
    show_logs_signal = pyqtSignal()
    exit_app_signal = pyqtSignal()

class SystemTray:
    def __init__(self, sip_gateway):
        self.sip_gateway = sip_gateway
        self.logger = logging.getLogger("system_tray")
        self.app = None
        self.tray_icon = None
        self.async_signals = None
        
        # Windows for different functions
        self.phone_window = None
        self.settings_window = None
        self.logs_window = None
        
        # Single instance check
        self.socket = None
        self.server = None
        
    def setup_single_instance(self):
        """Ensure only one instance is running"""
        try:
            self.socket = QLocalSocket()
            self.socket.connectToServer("sip_gateway_tray")
            if self.socket.waitForConnected(1000):
                # Another instance is already running
                QMessageBox.warning(None, "SIP Gateway", "Приложение уже запущено!")
                return False
            
            # This is the first instance - create server
            self.server = QLocalServer()
            self.server.listen("sip_gateway_tray")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка проверки единственного экземпляра: {e}")
            return True
    
    def create_icon(self) -> QIcon:
        """Create tray icon with status indicator"""
        try:
            # Create a simple icon programmatically
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # Background circle
            if self.sip_gateway and self.sip_gateway.sip_client.is_registered:
                painter.setBrush(Qt.GlobalColor.green)  # Connected
            else:
                painter.setBrush(Qt.GlobalColor.red)    # Disconnected
                
            painter.drawEllipse(2, 2, 28, 28)
            
            # Phone icon
            painter.setPen(Qt.GlobalColor.white)
            painter.setFont(QFont("Arial", 16))
            painter.drawText(8, 24, "📞")
            
            painter.end()
            
            return QIcon(pixmap)
            
        except Exception as e:
            self.logger.error(f"Ошибка создания иконки: {e}")
            # Fallback to simple icon
            return QIcon()
    
    def create_menu(self) -> QMenu:
        """Create system tray menu"""
        menu = QMenu()
        
        # Status info
        status_action = menu.addAction("Статус: Загрузка...")
        status_action.setEnabled(False)
        
        menu.addSeparator()
        
        # Phone controls
        phone_action = menu.addAction("📞 Открыть телефон")
        phone_action.triggered.connect(self.show_phone_window)
        
        menu.addSeparator()
        
        # Settings
        settings_action = menu.addAction("⚙️ Настройки")
        settings_action.triggered.connect(self.show_settings_window)
        
        # Logs
        logs_action = menu.addAction("📋 Логи")
        logs_action.triggered.connect(self.show_logs_window)
        
        menu.addSeparator()
        
        # Exit
        exit_action = menu.addAction("🚪 Выход")
        exit_action.triggered.connect(self.exit_application)
        
        return menu
    
    def show_phone_window(self):
        """Show demo phone in browser"""
        try:
            port = self.sip_gateway.config.get("rest_port", 8000)
            url = f"http://localhost:{port}/phone"
            webbrowser.open(url)
            self.logger.info(f"Открыт телефон в браузере: {url}")
        except Exception as e:
            self.logger.error(f"Ошибка открытия телефона: {e}")
            self.show_error_message("Не удалось открыть телефон в браузере")
    
    def show_settings_window(self):
        """Show settings dialog"""
        if not self.settings_window:
            self.settings_window = SettingsWindow(self.sip_gateway)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()
    
    def show_logs_window(self):
        """Show logs window"""
        if not self.logs_window:
            self.logs_window = LogsWindow(self.sip_gateway)
        self.logs_window.show()
        self.logs_window.raise_()
        self.logs_window.activateWindow()
    
    def exit_application(self):
        """Exit application gracefully"""
        reply = QMessageBox.question(
            None,
            "Подтверждение выхода",
            "Вы уверены, что хотите закрыть SIP Gateway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.logger.info("Запрошен выход из приложения")
            asyncio.create_task(self.sip_gateway.stop())
            QApplication.quit()
    
    def show_error_message(self, message: str):
        """Show error message"""
        QMessageBox.critical(None, "Ошибка", message)
    
    def show_notification(self, title: str, message: str):
        """Show system notification"""
        if self.tray_icon:
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)
    
    def update_status(self):
        """Update tray icon and status"""
        try:
            if self.tray_icon:
                # Update icon
                self.tray_icon.setIcon(self.create_icon())
                
                # Update tooltip
                status = "Подключен" if self.sip_gateway.sip_client.is_registered else "Отключен"
                in_call = " (В разговоре)" if self.sip_gateway.sip_client.is_in_call else ""
                tooltip = f"SIP Gateway - {status}{in_call}"
                self.tray_icon.setToolTip(tooltip)
                
        except Exception as e:
            self.logger.error(f"Ошибка обновления статуса: {e}")
    
    def run(self):
        """Start system tray application"""
        try:
            # Check if another instance is already running
            if not self.setup_single_instance():
                return False
            
            # Create Qt application
            self.app = QApplication(sys.argv)
            self.app.setQuitOnLastWindowClosed(False)
            
            # Create async signals bridge
            self.async_signals = AsyncSignal()
            self.async_signals.show_phone_signal.connect(self.show_phone_window)
            self.async_signals.show_settings_signal.connect(self.show_settings_window)
            self.async_signals.show_logs_signal.connect(self.show_logs_window)
            self.async_signals.exit_app_signal.connect(self.exit_application)
            
            # Create system tray icon
            self.tray_icon = QSystemTrayIcon()
            self.tray_icon.setIcon(self.create_icon())
            self.tray_icon.setToolTip("SIP Gateway - Загрузка...")
            
            # Create and set context menu
            menu = self.create_menu()
            self.tray_icon.setContextMenu(menu)
            
            # Connect double-click event
            self.tray_icon.activated.connect(self.on_tray_activated)
            
            # Show tray icon
            self.tray_icon.show()
            
            # Start status update timer
            self.status_timer = QTimer()
            self.status_timer.timeout.connect(self.update_status)
            self.status_timer.start(2000)  # Update every 2 seconds
            
            self.logger.info("Системный трей запущен")
            
            # Show startup notification
            self.show_notification("SIP Gateway", "Приложение запущено и работает в трее")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка запуска системного трея: {e}")
            return False
    
    def on_tray_activated(self, reason):
        """Handle tray icon activation"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_phone_window()
    
    def process_events(self):
        """Process Qt events (for async integration)"""
        if self.app:
            self.app.processEvents()

class SettingsWindow(QMainWindow):
    def __init__(self, sip_gateway):
        super().__init__()
        self.sip_gateway = sip_gateway
        self.setup_ui()
        
    def setup_ui(self):
        """Setup settings window UI"""
        self.setWindowTitle("Настройки SIP Gateway")
        self.setFixedSize(500, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # Tabs
        tabs = QTabWidget()
        layout.addWidget(tabs)
        
        # SIP Settings Tab
        sip_tab = QWidget()
        sip_layout = QFormLayout(sip_tab)
        
        self.sip_server_edit = QLineEdit()
        self.sip_port_edit = QSpinBox()
        self.sip_port_edit.setRange(1, 65535)
        self.sip_port_edit.setValue(5060)
        self.login_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.number_edit = QLineEdit()
        
        sip_layout.addRow("SIP Сервер:", self.sip_server_edit)
        sip_layout.addRow("SIP Порт:", self.sip_port_edit)
        sip_layout.addRow("Логин:", self.login_edit)
        sip_layout.addRow("Пароль:", self.password_edit)
        sip_layout.addRow("Номер:", self.number_edit)
        
        # WebSocket Settings Tab
        ws_tab = QWidget()
        ws_layout = QFormLayout(ws_tab)
        
        self.ws_host_edit = QLineEdit()
        self.ws_port_edit = QSpinBox()
        self.ws_port_edit.setRange(1, 65535)
        self.ws_port_edit.setValue(8765)
        
        ws_layout.addRow("WebSocket Хост:", self.ws_host_edit)
        ws_layout.addRow("WebSocket Порт:", self.ws_port_edit)
        
        # API Settings Tab
        api_tab = QWidget()
        api_layout = QFormLayout(api_tab)
        
        self.api_host_edit = QLineEdit()
        self.api_port_edit = QSpinBox()
        self.api_port_edit.setRange(1, 65535)
        self.api_port_edit.setValue(8000)
        
        api_layout.addRow("API Хост:", self.api_host_edit)
        api_layout.addRow("API Порт:", self.api_port_edit)
        
        # Logging Tab
        log_tab = QWidget()
        log_layout = QFormLayout(log_tab)
        
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_file_edit = QLineEdit()
        
        # Кнопка применения настроек логирования
        self.apply_log_btn = QPushButton("Применить уровень логирования")
        self.apply_log_btn.clicked.connect(self.apply_log_settings)
        
        log_layout.addRow("Уровень логирования:", self.log_level_combo)
        log_layout.addRow("Файл логов:", self.log_file_edit)
        log_layout.addRow(self.apply_log_btn)
        
        # Add tabs
        tabs.addTab(sip_tab, "SIP")
        tabs.addTab(ws_tab, "WebSocket")
        tabs.addTab(api_tab, "API")
        tabs.addTab(log_tab, "Логирование")
        
        # Buttons
        button_layout = QVBoxLayout()
        
        load_btn = QPushButton("Загрузить текущие настройки")
        load_btn.clicked.connect(self.load_current_settings)
        
        save_btn = QPushButton("Сохранить настройки")
        save_btn.clicked.connect(self.save_settings)
        
        test_sip_btn = QPushButton("Тест SIP подключения")
        test_sip_btn.clicked.connect(self.test_sip_connection)
        
        button_layout.addWidget(load_btn)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(test_sip_btn)
        
        layout.addLayout(button_layout)
        
        # Load current settings
        self.load_current_settings()
    
    def load_current_settings(self):
        """Load current settings into form"""
        try:
            config = self.sip_gateway.config
            
            # SIP settings
            self.sip_server_edit.setText(config.get("sip_settings.sip_server", ""))
            self.sip_port_edit.setValue(config.get("sip_settings.sip_port", 5060))
            self.login_edit.setText(config.get("sip_settings.login", ""))
            self.password_edit.setText(config.get("sip_settings.password", ""))
            self.number_edit.setText(config.get("sip_settings.number", ""))
            
            # WebSocket settings
            self.ws_host_edit.setText(config.get("websocket_host", "localhost"))
            self.ws_port_edit.setValue(config.get("websocket_port", 8765))
            
            # API settings
            self.api_host_edit.setText(config.get("rest_host", "localhost"))
            self.api_port_edit.setValue(config.get("rest_port", 8000))
            
            # Logging settings
            self.log_level_combo.setCurrentText(config.get("log_level", "INFO"))
            self.log_file_edit.setText(config.get("log_file", "logs/gateway.log"))
            
        except Exception as e:
            logging.error(f"Ошибка загрузки настроек: {e}")
    
    def save_settings(self):
        """Save settings from form"""
        try:
            settings = {
                "sip_settings": {
                    "sip_server": self.sip_server_edit.text(),
                    "sip_port": self.sip_port_edit.value(),
                    "login": self.login_edit.text(),
                    "password": self.password_edit.text(),
                    "number": self.number_edit.text()
                },
                "websocket_host": self.ws_host_edit.text(),
                "websocket_port": self.ws_port_edit.value(),
                "rest_host": self.api_host_edit.text(),
                "rest_port": self.api_port_edit.value(),
                "log_level": self.log_level_combo.currentText(),
                "log_file": self.log_file_edit.text()
            }
            
            # Save via REST API or directly
            asyncio.create_task(self._save_settings_async(settings))
            
            QMessageBox.information(self, "Успех", "Настройки сохранены!")
            
        except Exception as e:
            logging.error(f"Ошибка сохранения настроек: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить настройки: {e}")
    
    async def _save_settings_async(self, settings):
        """Async settings save"""
        try:
            for key, value in settings.items():
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        self.sip_gateway.config.set(f"{key}.{sub_key}", sub_value)
                else:
                    self.sip_gateway.config.set(key, value)
            
            self.sip_gateway.config.save_config()
            
        except Exception as e:
            logging.error(f"Ошибка асинхронного сохранения: {e}")
    
    def apply_log_settings(self):
        """Apply log level settings"""
        try:
            log_level = self.log_level_combo.currentText()
            
            # Send request to update log level
            asyncio.create_task(self._update_log_level(log_level))
            
        except Exception as e:
            logging.error(f"Ошибка применения настроек логирования: {e}")
    
    async def _update_log_level(self, log_level: str):
        """Update log level asynchronously"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    f"http://localhost:8000/api/logging/level",
                    json={"level": log_level}
                ) as response:
                    if response.status == 200:
                        logging.info(f"Уровень логирования изменен на: {log_level}")
                        QMessageBox.information(self, "Успех", f"Уровень логирования изменен на: {log_level}")
                    else:
                        error_text = await response.text()
                        logging.error(f"Ошибка изменения уровня логирования: {error_text}")
                        QMessageBox.critical(self, "Ошибка", f"Не удалось изменить уровень логирования: {error_text}")
        except Exception as e:
            logging.error(f"Ошибка обновления уровня логирования: {e}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка подключения: {e}")
    
    def test_sip_connection(self):
        """Test SIP connection with current settings"""
        QMessageBox.information(self, "Тест", "Тестирование SIP подключения...")

class LogsWindow(QMainWindow):
    def __init__(self, sip_gateway):
        super().__init__()
        self.sip_gateway = sip_gateway
        self.setup_ui()
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_logs)
        self.update_timer.start(2000)  # Update every 2 seconds
        
    def setup_ui(self):
        """Setup logs window UI"""
        self.setWindowTitle("Логи SIP Gateway")
        self.setFixedSize(800, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # Logs display
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setFont(QFont("Courier", 9))
        
        # Controls
        controls_layout = QVBoxLayout()
        
        refresh_btn = QPushButton("Обновить")
        refresh_btn.clicked.connect(self.update_logs)
        
        clear_btn = QPushButton("Очистить логи")
        clear_btn.clicked.connect(self.clear_logs)
        
        controls_layout.addWidget(refresh_btn)
        controls_layout.addWidget(clear_btn)
        
        layout.addWidget(self.logs_text)
        layout.addLayout(controls_layout)
        
        # Load initial logs
        self.update_logs()
    
    def update_logs(self):
        """Update logs display"""
        try:
            log_file = self.sip_gateway.config.get("log_file", "logs/gateway.log")
            if Path(log_file).exists():
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.logs_text.setPlainText(content)
                # Auto-scroll to bottom
                self.logs_text.moveCursor(self.logs_text.textCursor().End)
        except Exception as e:
            self.logs_text.setPlainText(f"Ошибка чтения логов: {e}")
    
    def clear_logs(self):
        """Clear log file"""
        try:
            log_file = self.sip_gateway.config.get("log_file", "logs/gateway.log")
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write("")
            self.update_logs()
            QMessageBox.information(self, "Успех", "Логи очищены!")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось очистить логи: {e}")

# Async integration helper
async def run_tray_with_async(sip_gateway):
    """Run system tray with async integration"""
    tray = SystemTray(sip_gateway)
    
    # Run tray in separate thread
    import threading
    
    def run_tray():
        tray.run()
        # Start Qt event loop
        if tray.app:
            tray.app.exec()
    
    tray_thread = threading.Thread(target=run_tray, daemon=True)
    tray_thread.start()
    
    # Process Qt events periodically in main async loop
    while True:
        tray.process_events()
        await asyncio.sleep(0.1)