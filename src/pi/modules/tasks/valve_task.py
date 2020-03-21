from modules.tasks.task import Task
from modules.drivers.arduino import Arduino
from modules.mcl.registry import Registry
from modules.mcl.flag import Flag
from modules.lib.enums import ValveType, SolenoidState, ActuationType
from modules.lib.errors import Error
import struct
from enum import Enum, auto

class ValveTask(Task):
    def __init__(self, registry: Registry, flag: Flag):
        self.name = "Valve Arduino"
        self.registry = registry
        self.flag = flag
        self.actuation_types = list(ActuationType)
        self.num_actuation_types = len(self.actuation_types)


    def begin(self, config):
        self.config = config["valves"]
        #TODO: Make sure that this is the same order that the arduino returns its data in
        self.valves = self.config["list"]
        self.solenoids = [loc for loc in self.valves[ValveType.SOLENOID]]
        self.num_solenoids = len(self.solenoids)
        self.arduino = Arduino(self.name, self.config)


    def get_solenoid_state(self, val):
        state_dict = {0: SolenoidState.OPEN, 1: SolenoidState.CLOSED}
        return state_dict[val] if val in state_dict else None


    def get_actuation_type(self, val):
        actuation_dict = {0: ActuationType.PULSE, 1: ActuationType.OPEN_VENT, 2: ActuationType.CLOSE_VENT, 3: ActuationType.NONE}
        return actuation_dict[val] if val in actuation_dict else None


    def get_float(self, data):
        byte_array = bytes(data)
        return struct.unpack('f', byte_array)[0]


    def get_command(self, loc, actuation_type):
        #Formula: idx1 * 16 + idx2
        loc_idx = self.solenoids.index(loc)
        actuation_idx = self.actuation_types.index(actuation_type)
        return loc_idx*16 + actuation_idx


    def read(self):
        data = self.arduino.read(self.num_solenoids*2)

        solenoid_states = [self.get_solenoid_state(val) for val in data[::2]]
        actuation_types = [self.get_actuation_type(val) for val in data[1::2]]
        assert(None not in solenoid_states)
        assert(None not in actuation_types)
        assert(len(solenoid_states) == self.num_solenoids)
        assert(len(actuation_types) == self.num_solenoids)

        for idx in range(self.num_solenoids):
            valve_loc = self.solenoids[idx]
            err = self.registry.put(("valve", ValveType.SOLENOID, valve_loc), solenoid_states[idx])
            assert(err is Error.NONE)
            err = self.registry.put(("valve_actuation", "actuation_type", ValveType.SOLENOID, valve_loc), actuation_types[idx])
            assert(err is Error.NONE)
            if actuation_types[idx] == ActuationType.NONE:
                err = self.registry.put(("valve_actuation", "actuation_priority", ValveType.SOLENOID, valve_loc), 0)
                assert(err is Error.NONE)


    #TODO: Fix the structure of this method, it's completely different from other classes and won't work properly
    def actuate(self):
        for loc in self.solenoids:
            err, actuation_type = self.flag.get(("solenoid", "actuation_type", loc))
            assert(err is Error.NONE)
            if actuation_type != ActuationType.NONE:
                err, actuation_priority = self.flag.get(("solenoid", "actuation_priority", loc))
                assert(err is Error.NONE)
                err, curr_priority, _ = self.registry.get(("valve_actuation", "actuation_priority", ValveType.SOLENOID, loc))
                #TODO: Decide, >= or > ?
                print(actuation_priority, curr_priority)
                if actuation_priority >= curr_priority:
                    print("Actuating")
                    command = self.get_command(loc, actuation_type)
                    self.arduino.write(command)
                    self.registry.put(("valve_actuation", "actuation_type", ValveType.SOLENOID, loc), actuation_type)
                    self.registry.put(("valve_actuation", "actuation_priority", ValveType.SOLENOID, loc), actuation_priority)
                    self.flag.put(("solenoid", "actuation_type", loc), ActuationType.NONE)
                    self.flag.put(("solenoid", "actuation_priority", loc), 0)