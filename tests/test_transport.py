import asyncio
from typing import Optional
from signalduino.transport import BaseTransport

class TestTransport(BaseTransport):
    def __init__(self):
        self._messages = []
        self._is_open = False
    
    async def open(self) -> None:
        self._is_open = True
    
    async def close(self) -> None:
        self._is_open = False
    
    def closed(self) -> bool:
        return not self._is_open
    
    async def write_line(self, data: str) -> None:
        pass
    
    async def readline(self) -> Optional[str]:
        if not self._messages:
            return None
        await asyncio.sleep(0)  # yield control to event loop
        return self._messages.pop(0)
    
    def add_message(self, msg: str):
        self._messages.append(msg)
    
    async def __aenter__(self) -> "TestTransport":
        await self.open()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()