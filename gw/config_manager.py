import json
import os
from typing import Any, Dict

class ConfigManager:
    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.config = self.load_config()
        
    def load_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации из файла"""
        default_config = {
            "websocket_host": "localhost",
            "websocket_port": 8765,
            "rest_host": "localhost",
            "rest_port": 8000,
            "log_level": "INFO",
            "log_file": "logs/gateway.log",
            "sip_settings": {
                "sip_server": "",
                "sip_port": 5060,
                "login": "",
                "password": "",
                "number": ""
            }
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    self._update_dict(default_config, user_config)
                    
        except Exception as e:
            print(f"Ошибка загрузки конфигурации: {e}")
            
        return default_config
    
    def _update_dict(self, original: Dict, update: Dict):
        """Рекурсивное обновление словаря"""
        for key, value in update.items():
            if isinstance(value, dict) and key in original and isinstance(original[key], dict):
                self._update_dict(original[key], value)
            else:
                original[key] = value
    
    def save_config(self):
        """Сохранение конфигурации в файл"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Ошибка сохранения конфигурации: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """Получение значения конфигурации"""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
                
        return value
    
    def set(self, key: str, value: Any):
        """Установка значения конфигурации"""
        keys = key.split('.')
        config = self.config
        
        for k in keys[:-1]:
            if k not in config or not isinstance(config[k], dict):
                config[k] = {}
            config = config[k]
            
        config[keys[-1]] = value
    
    def get_all(self) -> Dict[str, Any]:
        """Получить всю конфигурацию"""
        return self.config.copy()
    
    def reset_to_defaults(self):
        """Сброс конфигурации к значениям по умолчанию"""
        self.config = self.load_config()
        return self.save_config()
    
    def validate_config(self) -> bool:
        """Валидация конфигурации"""
        try:
            # Проверка обязательных полей SIP, если они заполнены
            sip_settings = self.get("sip_settings", {})
            if sip_settings.get("sip_server"):
                required_fields = ["sip_server", "login", "password", "number"]
                for field in required_fields:
                    if not sip_settings.get(field):
                        return False
            
            # Проверка числовых полей
            if not isinstance(self.get("websocket_port"), int) or not (1 <= self.get("websocket_port") <= 65535):
                return False
            if not isinstance(self.get("rest_port"), int) or not (1 <= self.get("rest_port") <= 65535):
                return False
            if not isinstance(self.get("sip_settings.sip_port"), int) or not (1 <= self.get("sip_settings.sip_port") <= 65535):
                return False
            
            # Проверка уровня логирования
            valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
            if self.get("log_level") not in valid_log_levels:
                return False
                
            return True
            
        except Exception:
            return False