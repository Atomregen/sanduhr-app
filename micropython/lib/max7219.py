"""
MicroPython max7219 cascadable 8x8 LED matrix driver
https://github.com/mcauser/micropython-max7219

MIT License
Copyright (c) 2017 Mike Causer

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from micropython import const
import framebuf

# MAX7219 Register-Adressen
_NOOP = const(0)
_DIGIT0 = const(1)
_DECODEMODE = const(9)
_INTENSITY = const(10)
_SCANLIMIT = const(11)
_SHUTDOWN = const(12)
_DISPLAYTEST = const(15)


class Matrix8x8:
    """
    Treiber für kaskadierbare MAX7219 8x8 LED-Matrizen.
    
    Diese Klasse stellt eine FrameBuffer-Schnittstelle zur Verfügung, um Grafiken
    und Text auf den Matrizen darzustellen.
    """

    def __init__(self, spi, cs, num):
        """
        Initialisiert den Treiber.

        Args:
            spi (SPI): Ein initialisiertes SPI-Objekt.
            cs (Pin): Der Chip-Select-Pin.
            num (int): Die Anzahl der kaskadierten 8x8-Matrizen.
        """
        self.spi = spi
        self.cs = cs
        self.num = num
        self.cs.init(cs.OUT, True)
        
        # Buffer für die Display-Daten
        self.buffer = bytearray(8 * self.num)
        self.width = 8 * self.num
        
        # Erstelle einen FrameBuffer, der auf unseren internen Buffer zugreift
        fb = framebuf.FrameBuffer(self.buffer, self.width, 8, framebuf.MONO_HLSB)
        self.framebuf = fb

        # FrameBuffer-Methoden direkt auf dieser Klasse verfügbar machen
        self.fill = fb.fill
        self.pixel = fb.pixel
        self.hline = fb.hline
        self.vline = fb.vline
        self.line = fb.line
        self.rect = fb.rect
        self.fill_rect = fb.fill_rect
        self.text = fb.text
        self.scroll = fb.scroll
        self.blit = fb.blit
        
        self.init()

    def _write(self, command, data):
        """Sendet einen Befehl und Daten an alle kaskadierten Chips."""
        self.cs(0)
        for _ in range(self.num):
            self.spi.write(bytearray([command, data]))
        self.cs(1)

    def init(self):
        """Initialisiert alle MAX7219-Chips mit Standardwerten."""
        for command, data in (
            (_SHUTDOWN, 0),       # Turn off display
            (_DISPLAYTEST, 0),    # No display test
            (_SCANLIMIT, 7),      # Scan all 8 digits
            (_DECODEMODE, 0),     # No BCD decode
            (_SHUTDOWN, 1),       # Turn on display
        ):
            self._write(command, data)

    def brightness(self, value):
        """
        Setzt die Helligkeit des Displays.

        Args:
            value (int): Ein Wert von 0 bis 15.
        """
        if not 0 <= value <= 15:
            raise ValueError("Brightness must be between 0 and 15.")
        self._write(_INTENSITY, value)

    def show(self):
        """Überträgt den Inhalt des Framebuffers auf das Display."""
        # Schreibe jede der 8 Zeilen in die entsprechenden Register
        for y in range(8):
            self.cs(0)
            for m in range(self.num):
                # Die Daten sind im Buffer so angeordnet, dass sie direkt
                # an die kaskadierten Module gesendet werden können.
                self.spi.write(bytearray([_DIGIT0 + y, self.buffer[(y * self.num) + m]]))
            self.cs(1)