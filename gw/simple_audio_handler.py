import asyncio
import logging
from typing import Optional, Callable
import pyaudio
import queue

class SimpleAudioHandler:
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.audio_format = pyaudio.paInt16
        self.channels = 1
        self.rate = 8000
        self.chunk = 160
        self.is_running = False
        self.audio_queue = queue.Queue()
        self.logger = logging.getLogger("audio_handler")
        
        # Callback for sending audio data
        self.send_audio_callback = None
        
    def set_send_audio_callback(self, callback: Callable):
        """Set callback for sending audio data"""
        self.send_audio_callback = callback
        
    async def start_audio_streams(self):
        """Start audio input and output streams"""
        try:
            # Only start output stream for simplicity
            # Input can be handled on-demand
            self.output_stream = self.audio.open(
                format=self.audio_format,
                channels=self.channels,
                rate=self.rate,
                output=True,
                frames_per_buffer=self.chunk
            )
            
            self.is_running = True
            self.logger.info("Аудио выходной поток запущен")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка запуска аудио потоков: {e}")
            return False
    
    async def start_input_stream(self):
        """Start audio input stream on-demand"""
        try:
            if not self.input_stream:
                self.input_stream = self.audio.open(
                    format=self.audio_format,
                    channels=self.channels,
                    rate=self.rate,
                    input=True,
                    frames_per_buffer=self.chunk
                )
                self.logger.info("Аудио входной поток запущен")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка запуска входного аудио потока: {e}")
            return False
    
    async def read_audio(self) -> Optional[bytes]:
        """Read audio data from microphone"""
        try:
            if self.is_running and self.input_stream:
                data = self.input_stream.read(self.chunk, exception_on_overflow=False)
                
                # Send to callback if set
                if self.send_audio_callback:
                    asyncio.create_task(self.send_audio_callback(data))
                
                return data
            return None
        except Exception as e:
            self.logger.error(f"Ошибка чтения аудио: {e}")
            return None
    
    async def write_audio(self, data: bytes):
        """Write audio data to speaker output"""
        try:
            if self.is_running and self.output_stream and data:
                self.output_stream.write(data)
        except Exception as e:
            self.logger.error(f"Ошибка записи аудио: {e}")
    
    async def stop_audio_streams(self):
        """Stop audio streams"""
        try:
            self.is_running = False
            
            if self.input_stream:
                self.input_stream.stop_stream()
                self.input_stream.close()
                self.input_stream = None
            
            if self.output_stream:
                self.output_stream.stop_stream()
                self.output_stream.close()
                self.output_stream = None
            
            self.audio.terminate()
            self.logger.info("Аудио потоки остановлены")
            
        except Exception as e:
            self.logger.error(f"Ошибка остановки аудио потоков: {e}")
    
    def get_audio_info(self) -> dict:
        """Get audio device information"""
        try:
            info = {
                'input_devices': [],
                'output_devices': [],
                'default_sample_rate': self.rate,
                'default_channels': self.channels,
                'status': 'running' if self.is_running else 'stopped'
            }
            
            for i in range(self.audio.get_device_count()):
                device_info = self.audio.get_device_info_by_index(i)
                if device_info['maxInputChannels'] > 0:
                    info['input_devices'].append({
                        'index': i,
                        'name': device_info['name'],
                        'max_channels': device_info['maxInputChannels']
                    })
                if device_info['maxOutputChannels'] > 0:
                    info['output_devices'].append({
                        'index': i,
                        'name': device_info['name'],
                        'max_channels': device_info['maxOutputChannels']
                    })
            
            return info
            
        except Exception as e:
            self.logger.error(f"Ошибка получения информации об аудио устройствах: {e}")
            return {'error': str(e)}