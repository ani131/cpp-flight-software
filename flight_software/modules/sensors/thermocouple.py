import yaml
import time
import Adafruit_GPIO
# Local Imports
from . import Sensor, SensorStatus, SensorType

try:
# if REAL:
    from Adafruit_MAX31856 import MAX31856 as MAX31856
except:
    print("Skipping thermocouple on non-pi...")
    REAL = False
else:
    print("Loaded thermocouple")
    REAL = True

class PsuedoThermocouple():

    def read_internal_temp_c(self):
        return 1

    def read_temp_c(self):
        return 2


import os
print(os.listdir("."))

class Thermocouple(Sensor):

    def __init__(self, port, device, location):
        """
        Initializes attributes needed for thermocouple sensor class
        :param port: SPi serial port
        :param device: Which device is being communicated with
        :param location: Where temperature is being taken
        """
        SPI_PORT = port
        SPI_DEVICE = device
        self.sensor = MAX31856(hardware_spi=Adafruit_GPIO.SPI.SpiDev(SPI_PORT, SPI_DEVICE), tc_type=MAX31856.MAX31856_K_TYPE) \
            if REAL else PsuedoThermocouple()
        self._name = "Thermocouple"
        self._location = location
        self._status = SensorStatus.Safe
        self._sensor_type = SensorType.Temperature
        self.data = {}
        self.timestamp = None  # Indication of when last data was calculated
        self.ABORT = True

        with open("./boundaries.yaml" if REAL else "flight_software/boundaries.yaml", 'r') as ymlfile:
            cfg = yaml.load(ymlfile)
        assert location in cfg['thermocouple']
        self.boundaries = {}
        self.boundaries[SensorStatus.Safe] = cfg['thermocouple'][location]['safe']
        self.boundaries[SensorStatus.Warn] = cfg['thermocouple'][location]['warn']
        self.boundaries[SensorStatus.Crit] = cfg['thermocouple'][location]['crit']

    def internal(self):
        return self.sensor.read_internal_temp_c()

    def temp(self):
        return self.sensor.read_temp_c()

    def get_data(self):
        """ :return: Set of internal temperature, external temperature, and timestamp"""
        data = {}
        data["internal"] = self.internal()
        data["temp"] = self.temp()
        data["timestamp"] = time.time()
        self.timestamp = time.time()
        self.data = data
        return data

    def check(self):
        """
        Constantly runs in the thread, calling get_data which is checked to set
        status to safe, warning, or critical

        This method should be constantly running in a thread, and should be the
        only thing calling get_data
        """
        while True:
            data = self.get_data()
            if data["temp"] >= self.boundaries[SensorStatus.Safe][0] and data["temp"] <= self.boundaries[SensorStatus.Safe][1]:
                self._status = SensorStatus.Safe
            elif data["temp"] >= self.boundaries[SensorStatus.Warn][0] and data["temp"] <= self.boundaries[SensorStatus.Warn][1]:
                self._status = SensorStatus.Warn
            else:
                self._status = SensorStatus.Crit

    def name(self):
        return self._name

    def location(self):
        return self._location

    def status(self):
        return self._status

    def sensor_type(self):
        return self._sensor_type

    def log(self):
        pass