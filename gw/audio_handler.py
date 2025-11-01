import asyncio
import logging
from typing import Optional, Callable
import pyaudio
import threading
import queue
from concurrent.futures import ThreadPoolExecutor

class AudioHandler:
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
        self._executor = ThreadPoolExecutor(max_workers=2)
        
    def set_send_audio_callback(self, callback: Callable):
        """Set callback for sending audio data"""
        self.send_audio_callback = callback
        
    async def start_audio_streams(self):
        """Start audio input and output streams"""
        try:
            # Input stream (microphone) - без callback для простоты
            self.input_stream = self.audio.open(
                format=self.audio_format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )
            
            # Output stream (speaker)
            self.output_stream = self.audio.open(
                format=self.audio_format,
                channels=self.channels,
                rate=self.rate,
                output=True,
                frames_per_buffer=self.chunk
            )
            
            self.is_running = True
            
            # Start audio processing threads
            self.input_thread = threading.Thread(target=self._input_processing_loop, daemon=True)
            self.output_thread = threading.Thread(target=self._output_processing_loop, daemon=True)
            
            self.input_thread.start()
            self.output_thread.start()
            
            self.logger.info("Аудио потоки запущены")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка запуска аудио потоков: {e}")
            return False
    
    def _input_processing_loop(self):
        """Process audio input in separate thread"""
        while self.is_running:
            try:
                # Read audio from microphone
                if self.input_stream:
                    audio_data = self.input_stream.read(self.chunk, exception_on_overflow=False)
                    
                    # Send audio data via callback if set
                    if self.send_audio_callback and audio_data:
                        # Use thread pool to handle async callback
                        future = asyncio.run_coroutine_threadsafe(
                            self.send_audio_callback(audio_data),
                            asyncio.get_event_loop()
                        )
                        # Don't wait for completion to avoid blocking
                        
            except Exception as e:
                if self.is_running:  # Only log if still running
                    self.logger.error(f"Ошибка чтения аудио: {e}")
                break
    
    def _output_processing_loop(self):
        """Process audio output in separate thread"""
        while self.is_running:
            try:
                # Process audio from queue (e.g., from SIP)
                if not self.audio_queue.empty() and self.output_stream:
                    audio_data = self.audio_queue.get_nowait()
                    if audio_data:
                        self.output_stream.write(audio_data)
                else:
                    # Small sleep to prevent high CPU usage
                    threading.Event().wait(0.01)
                    
            except Exception as e:
                if self.is_running:  # Only log if still running
                    self.logger.error(f"Ошибка в output processing loop: {e}")
    
    async def write_audio(self, data: bytes):
        """Write audio data to speaker output"""
        try:
            if self.is_running and self.output_stream:
                # Put audio data in queue for processing
                self.audio_queue.put(data)
        except Exception as e:
            self.logger.error(f"Ошибка записи аудио: {e}")
    
    async def read_audio(self) -> Optional[bytes]:
        """Read audio data from microphone (alternative method)"""
        try:
            if self.is_running and self.input_stream:
                # This is a direct read method that can be used instead of the loop
                data = self.input_stream.read(self.chunk, exception_on_overflow=False)
                return data
        except Exception as e:
            self.logger.error(f"Ошибка чтения аудио: {e}")
            return None
    
    async def stop_audio_streams(self):
        """Stop audio streams"""
        try:
            self.is_running = False
            
            # Wait a bit for threads to finish
            await asyncio.sleep(0.1)
            
            if self.input_stream:
                self.input_stream.stop_stream()
                self.input_stream.close()
            
            if self.output_stream:
                self.output_stream.stop_stream()
                self.output_stream.close()
            
            self.audio.terminate()
            self._executor.shutdown(wait=False)
            
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
                        'max_channels': device_info['maxInputChannels'],
                        'sample_rate': device_info['defaultSampleRate']
                    })
                if device_info['maxOutputChannels'] > 0:
                    info['output_devices'].append({
                        'index': i,
                        'name': device_info['name'],
                        'max_channels': device_info['maxOutputChannels'],
                        'sample_rate': device_info['defaultSampleRate']
                    })
            
            return info
            
        except Exception as e:
            self.logger.error(f"Ошибка получения информации об аудио устройствах: {e}")
            return {'error': str(e)}