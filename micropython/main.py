# #############################################################################
# Sanduhr / Houerglas
# Written with the help of Google Gemini
# #############################################################################

import utime
import random
from machine import Pin, SPI, I2C
import ujson

# Libraries for asynchronous Bluetooth
import bluetooth
import aioble
import asyncio

# Required libraries
import max7219
import MPU6050
import matrixsand

# #############################################################################
# CONFIGURATION
# #############################################################################

# Default initial values (used only on the very first start or in case of an error)
DEFAULT_ANZAHL_SANDKOERNER = 60
DEFAULT_GESAMTDAUER_SEKUNDEN = 60
SETTINGS_FILE = "sanduhr_settings.json"

PHYSIK_UPDATE_INTERVALL_MS = 20

# UUIDs for the BLE Service
_SANDUHR_SERVICE_UUID = bluetooth.UUID("4A980000-8580-425B-A2A8-33353579C6F5")
_ANZAHL_CHAR_UUID = bluetooth.UUID("4A980001-8580-425B-A2A8-33353579C6F5")
_DAUER_CHAR_UUID = bluetooth.UUID("4A980002-8580-425B-A2A8-33353579C6F5")

# #############################################################################
# Hourglass Class
# #############################################################################

class Sanduhr:
    def __init__(self, display, sensor):
        self.display = display
        self.sensor = sensor
      
        self.anzahl_koerner = DEFAULT_ANZAHL_SANDKOERNER
        self.dauer_sekunden = DEFAULT_GESAMTDAUER_SEKUNDEN
        
        self.sand_kolben_1 = matrixsand.MatrixSand(8, 8)
        self.sand_kolben_2 = matrixsand.MatrixSand(8, 8)

        self.updated1 = False
        self.updated2 = False
        
        self.fall_intervall_ms = 0
        self.naechster_geplanter_fall = 0
        self.letzte_fallrichtung_positiv = True
        self.gefallene_koerner = 0
        self.letzter_print_zeitpunkt = 0
        
        self._initialisiere_hardware_und_sand()

    def _load_settings(self):
        """Tries to load the settings from a JSON file."""
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = ujson.load(f)
                self.anzahl_koerner = settings.get('anzahl', DEFAULT_ANZAHL_SANDKOERNER)
                self.dauer_sekunden = settings.get('dauer', DEFAULT_GESAMTDAUER_SEKUNDEN)
                print(f"Settings loaded from '{SETTINGS_FILE}'.")
        except (OSError, ValueError):
            print(f"'{SETTINGS_FILE}' not found. Using default values.")
            self._save_settings() # Creates the file with default values

    def _save_settings(self):
        """Saves the current settings to a JSON file."""
        try:
            with open(SETTINGS_FILE, 'w') as f:
                ujson.dump({
                    'anzahl': self.anzahl_koerner,
                    'dauer': self.dauer_sekunden
                }, f)
            print(f"Settings saved to '{SETTINGS_FILE}'.")
        except OSError as e:
            print(f"Error saving settings: {e}")

    def _initialisiere_hardware_und_sand(self):
        self.sensor.wake()
        self.sensor.write_accel_range(0)
        self.sensor.write_lpf_range(0)
        self.display.brightness(1)
        self._load_settings() # Load settings right at the start
        self.reset_simulation()

    def _berechne_intervall(self):
        if self.anzahl_koerner > 0:
            self.fall_intervall_ms = (self.dauer_sekunden * 1000) / self.anzahl_koerner
        else:
            self.fall_intervall_ms = float('inf')
        print(f"New setting: {self.anzahl_koerner} grains, {self.dauer_sekunden}s. Interval: {self.fall_intervall_ms:.0f}ms")

    def reset_simulation(self):
        """Resets the hourglass, detects the orientation, and restarts the timer."""
        self._berechne_intervall()
        self.sand_kolben_1._grains = [False] * 64
        self.sand_kolben_2._grains = [False] * 64
        
        # Determine which bulb is currently on top
        try:
            ax, ay, _ = self.sensor.read_accel_data()
            yy = -ax + ay
            self.letzte_fallrichtung_positiv = yy > 0
        except Exception:
            self.letzte_fallrichtung_positiv = True # Default assumption in case of sensor error
            
        print(f"Start orientation detected: Bulb {'1 (A)' if self.letzte_fallrichtung_positiv else '2 (B)'} is on top.")

        # Select the BOTTOM bulb to fill it
        unterer_kolben = self.sand_kolben_2 if self.letzte_fallrichtung_positiv else self.sand_kolben_1
        
        moegliche_positionen = list(range(64))
        for _ in range(self.anzahl_koerner):
            if not moegliche_positionen: break
            wahl_index = random.randint(0, len(moegliche_positionen) - 1)
            position = moegliche_positionen.pop(wahl_index)
            unterer_kolben[position % 8, position // 8] = True
            
        self.naechster_geplanter_fall = utime.ticks_add(utime.ticks_ms(), int(self.fall_intervall_ms))
        # Since the sand is at the bottom, no grains have "fallen" yet
        self.gefallene_koerner = 0
        self.updated1 = self.updated2 = False
        self._zeichne_sand()
        print(f"Hourglass reset with {sum(self.sand_kolben_1._grains) + sum(self.sand_kolben_2._grains)} grains.")

    def set_anzahl_koerner(self, anzahl):
        self.anzahl_koerner = max(1, min(60, anzahl))
        self._save_settings() # Save on change
        self.reset_simulation()
        
    def set_dauer_sekunden(self, dauer):
        self.dauer_sekunden = max(5, min(3600, dauer))
        self._save_settings() # Save on change
        self.reset_simulation()

    def _zeichne_sand(self):
        self.display.fill(0)
        for x in range(8):
            for y in range(8):
                self.display.pixel(y, x, self.sand_kolben_1[x, y])
                self.display.pixel(y + 8, x, self.sand_kolben_2[x, y])
        self.display.show()

    def _update_simulation(self):
        """
        Performs a simulation step.
        This method now corresponds exactly to the logic from sanduhr3.py
        """
        try:
            ax, ay, az = self.sensor.read_accel_data()
        except Exception:
            return False

        xx = -ax - ay
        yy = -ax + ay
        
        transfer_erfolgt = False
        
        # Flip detection and timer reset
        aktuelle_richtung_positiv = yy > 0
        if aktuelle_richtung_positiv != self.letzte_fallrichtung_positiv:
            self.naechster_geplanter_fall = utime.ticks_add(utime.ticks_ms(), int(self.fall_intervall_ms))
            self.gefallene_koerner = sum(self.sand_kolben_2._grains) if aktuelle_richtung_positiv else sum(self.sand_kolben_1._grains)
            self.letzte_fallrichtung_positiv = aktuelle_richtung_positiv

        jetzt = utime.ticks_ms()
        if utime.ticks_diff(jetzt, self.naechster_geplanter_fall) > 0:
            if yy > 0.8 and self.sand_kolben_1[7,7] and not self.sand_kolben_2[0,0]:
                self.sand_kolben_1[7,7] = False; self.sand_kolben_2[0,0] = True
                transfer_erfolgt = True
            elif yy < -0.8 and self.sand_kolben_2[0,0] and not self.sand_kolben_1[7,7]:
                self.sand_kolben_2[0,0] = False; self.sand_kolben_1[7,7] = True
                transfer_erfolgt = True

            if transfer_erfolgt:
                self.naechster_geplanter_fall = utime.ticks_add(self.naechster_geplanter_fall, int(self.fall_intervall_ms))
                self.gefallene_koerner += 1
        
        updated1 = self.sand_kolben_1.iterate((xx, yy, az))
        updated2 = self.sand_kolben_2.iterate((xx, yy, az))
        return updated1 or updated2 or transfer_erfolgt

    async def run_logic(self):
        while True:
            if self._update_simulation():
                self._zeichne_sand()
            
            jetzt = utime.ticks_ms()
            if utime.ticks_diff(jetzt, self.letzter_print_zeitpunkt) > 250:
                verbleibende_ms = utime.ticks_diff(self.naechster_geplanter_fall, jetzt)
                if verbleibende_ms < 0: verbleibende_ms = 0
                
                koerner_im_oberen_kolben = self.anzahl_koerner - self.gefallene_koerner
                if koerner_im_oberen_kolben <= 0:
                     print(f"Hourglass has run out.                                       \r", end="")
                else:
                     print(f"Next grain ({self.gefallene_koerner + 1}/{self.anzahl_koerner}) falls in: {verbleibende_ms / 1000:.1f}s   \r", end="")
                
                self.letzter_print_zeitpunkt = jetzt

            await asyncio.sleep_ms(PHYSIK_UPDATE_INTERVALL_MS)

# #############################################################################
# Asynchronous BLE Logic
# #############################################################################

sanduhr_service = aioble.Service(_SANDUHR_SERVICE_UUID)
anzahl_char = aioble.Characteristic(sanduhr_service, _ANZAHL_CHAR_UUID, read=True, write=True, notify=True, capture=True)
dauer_char = aioble.Characteristic(sanduhr_service, _DAUER_CHAR_UUID, read=True, write=True, notify=True, capture=True)
aioble.register_services(sanduhr_service)

async def peripheral_task(sanduhr_obj):
    print("Starting BLE server...")
    while True:
        try:
            async with await aioble.advertise(
                250000, name="Sanduhr", services=[_SANDUHR_SERVICE_UUID]
            ) as connection:
                print(f"Connection established from: {connection.device}")
                print("Sending current state to the app...")
                
                anzahl_data = sanduhr_obj.anzahl_koerner.to_bytes(4, 'little')
                anzahl_char.write(anzahl_data, send_update=True)
                await asyncio.sleep_ms(50)
                
                dauer_data = sanduhr_obj.dauer_sekunden.to_bytes(4, 'little')
                dauer_char.write(dauer_data, send_update=True)
                
                print("Current state sent.")
                await connection.disconnected()
                print(f"Connection to {connection.device} lost.")
        
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"Error in peripheral task: {e}")
            await asyncio.sleep_ms(2000)

async def anzahl_write_handler(sanduhr_obj):
    while True:
        try:
            _, data = await anzahl_char.written()
            neue_anzahl = int.from_bytes(data, 'little')
            print(f"\nBLE: Received new grain count: {neue_anzahl}")
            sanduhr_obj.set_anzahl_koerner(neue_anzahl)
        except Exception: await asyncio.sleep_ms(100)

async def dauer_write_handler(sanduhr_obj):
    while True:
        try:
            _, data = await dauer_char.written()
            neue_dauer = int.from_bytes(data, 'little')
            print(f"\nBLE: Received new duration: {neue_dauer}")
            sanduhr_obj.set_dauer_sekunden(neue_dauer)
        except Exception: await asyncio.sleep_ms(100)

# #############################################################################
# MAIN PROGRAM (Asynchronous)
# #############################################################################

async def main():
    spi = SPI(1, baudrate=10000000, sck=Pin(8), mosi=Pin(10))
    cs = Pin(9, Pin.OUT)
    i2c = I2C(0, sda=Pin(6), scl=Pin(7), freq=400000)
    display = max7219.Matrix8x8(spi, cs, 2)
    mpu = MPU6050.MPU6050(i2c)
    
    # The constructor is now called without initial values, as they are loaded
    sanduhr = Sanduhr(display=display, sensor=mpu)
    
    try:
        await asyncio.gather(
            sanduhr.run_logic(),
            peripheral_task(sanduhr),
            anzahl_write_handler(sanduhr),
            dauer_write_handler(sanduhr)
        )
    except KeyboardInterrupt:
        print("Program is being terminated.")
    finally:
        display.fill(0)
        display.show()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program stopped.")
