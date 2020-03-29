import json, enum, time
from heapq import heappop
from modules.mcl.flag import Flag
from modules.lib.errors import Error
from modules.mcl.registry import Registry
from modules.lib.packet import Packet, Log, LogPriority
from modules.lib.enums import SensorType, SensorLocation, ValveLocation, ActuationType, ValveType, Stage

class TelemetryControl(): 
    def __init__(self, registry: Registry, flag: Flag):
        self.registry = registry
        self.flag = flag
        self.funcs = {
            "heartbeat": self.heartbeat,
            "hard_abort": self.hard_abort,
            "soft_abort": self.soft_abort,
            "solenoid_actuate": self.solenoid_actuate,
            "sensor_request": self.sensor_request,
            "valve_request": self.valve_request,
            "progress": self.progress,
            "test": self.test,
        }
        self.arguments = {
            "heartbeat": (),
            "hard_abort": (),
            "soft_abort": (),
            "solenoid_actuate": (("valve_location", ValveLocation), ("actuation_type", ActuationType), ("priority", int)),
            "sensor_request": (("sensor_type", SensorType), ("sensor_location", SensorLocation)),
            "valve_request": (("valve_type", ValveType), ("valve_location", ValveLocation)),
            "progress": (),
            "test": (("response", str),),
        }
    

    def begin(self, config: dict):
        self.config = config
        self.sensors = config["sensors"]["list"]
        self.valves = config["valves"]["list"]


    def execute(self) -> Error:
        #TODO: Check if resetting telemetry works
        _, status, timestamp = self.registry.get(("telemetry", "status"))
        if not status:
            self.flag.put(("telemetry", "reset"), True)
            return None

        self.flag.put(("telemetry", "reset"), False)
        _, telem_queue, _ = self.registry.get(("telemetry", "ingest_queue"))
        while telem_queue:
            packet = heappop(telem_queue)
            #TODO: Figure out if the command from a log is outdated
            for log in packet.logs:
                print(log)
                err = self.ingest(log)
            # Clear the ingest queue (because we just ingested everything)
            self.registry.put(("telemetry", "ingest_queue"), [])


    def ingest(self, log: Log):
        #TODO: Send message back to GS saying that an invalid message was sent
        header = log.header
        if header in self.funcs:
            func = self.funcs[header]
            args = []
            assert(header in self.arguments)
            for arg_name, arg_type in self.arguments[header]:
                if arg_name not in log.message:
                    print("Invalid argument", arg_name)
                    log = Log(header="response", message={"header": "Missing argument", "argument": arg_name})
                    self.enqueue(log, LogPriority.CRIT)
                    return Error.INVALID_ARGUMENT_ERROR
                if issubclass(arg_type, enum.Enum):
                    if log.message[arg_name] not in [x.value for x in arg_type]:
                        print("Invalid argument", arg_name, arg_type)
                        log = Log(header="response", message={"header": "Invalid argument type", "argument": arg_name, "argument type": str(arg_type)})
                        self.enqueue(log, LogPriority.CRIT)
                        return Error.INVALID_ARGUMENT_ERROR
                elif not isinstance(log.message[arg_name], arg_type):
                    print("Invalid argument", arg_name, arg_type)
                    log = Log(header="response", message={"header": "Invalid argument type", "argument": arg_name, "argument type": str(arg_type)})
                    self.enqueue(log, LogPriority.CRIT)
                    return Error.INVALID_ARGUMENT_ERROR
                args.append(arg_type(log.message[arg_name]))
            func(*args)
            return Error.NONE
        else:
            print("Invalid header")
            log = Log(header="response", message={"header": "Invalid telemetry header", "telemetry_header": header})
            self.enqueue(log, LogPriority.CRIT)
            return Error.INVALID_HEADER_ERROR


    def enqueue(self, log: Log, level: LogPriority):
        _, queue = self.flag.get(("telemetry", "enqueue"))
        queue.append((log, level))
        self.flag.put(("telemetry", "enqueue"), queue)


    def heartbeat(self):
        print("Heartbeating")
        self.enqueue(Log(header="heartbeat", message={"response": "OK"}), level=LogPriority.INFO)


    def hard_abort(self):
        self.flag.put(("general", "hard_abort"), True)
        log = Log(header="response", message={"header": "Hard abort", "status": "Success", "description": "Rocket is undergoing hard abort"})
        self.enqueue(log, LogPriority.CRIT)


    def soft_abort(self):
        self.flag.put(("general", "soft_abort"), True)
        log = Log(header="response", message={"header": "Soft abort", "status": "Success", "description": "Rocket is undergoing soft abort"})
        self.enqueue(log, LogPriority.CRIT)


    def solenoid_actuate(self, valve_location: ValveLocation, actuation_type: ActuationType, priority: int) -> Error:
        err, current_priority, timestamp = self.registry.get(("valve_actuation", "actuation_priority", ValveType.SOLENOID, valve_location), allow_error=True)
        if err != Error.NONE:
            # Send message back to gs saying it was an invalid message
            log = Log(header="response", message={"header": "Valve actuation", "status": "Failure", "description": "Unable to find solenoid in " + valve_location + " with actuation type " + actuation_type})
            self.enqueue(log, LogPriority.CRIT)
            return Error.REQUEST_ERROR

        if priority <= current_priority:
            # Send message back to gs saying that the request was made w/ too little priority
            log = Log(header="response", message={"header": "Valve actuation", "status": "Failure", "description": "Too little priority to actuate solenoid at " + valve_location + " with actuation type " + actuation_type + " at priority " + str(priority)})
            self.enqueue(log, LogPriority.CRIT)
            return Error.PRIORITY_ERROR

        print("Actuating solenoid at {} with actuation type {}".format(valve_location, actuation_type))

        self.flag.put(("solenoid", "actuation_type", valve_location), actuation_type)
        self.flag.put(("solenoid", "actuation_priority", valve_location), priority)

        log = Log(header="response", message={"header": "Valve actuation", "status": "Success", "description": "Actuated solenoid at " + valve_location + " with actuation type " + actuation_type + " at priority " + str(priority)})
        self.enqueue(log, LogPriority.CRIT)


    def sensor_request(self, sensor_type: SensorType, sensor_location: SensorLocation) -> Error:
        err, value, timestamp = self.registry.get(("sensor_measured", sensor_type, sensor_location), allow_error=True)
        if err != Error.NONE:
            # Send message back to gs saying it was an invalid message            
            log = Log(header="response", message={"header": "Sensor data", "status": "Failure", "description": "Unable to find " + sensor_type + " in " + sensor_location})
            self.enqueue(log, LogPriority.CRIT)
            return Error.REQUEST_ERROR

        _, kalman_value, _ = self.registry.get(("sensor_normalized", sensor_type, sensor_location), allow_error=True)
        _, status, _ = self.registry.get(("sensor_status", sensor_type, sensor_location))
        log = Log(header="response", message={"header": "Sensor data", "status": "Success", "type": sensor_type, "location": sensor_location, "value": (value, kalman_value), "sensor_status": status, "last_updated": timestamp})
        self.enqueue(log, LogPriority.INFO)


    def valve_request(self, valve_type: ValveType, valve_location: ValveLocation) -> Error: 
        err, value, timestamp = self.registry.get(("valve", valve_type, valve_location), allow_error=True)
        if err != Error.NONE:
            # Send message back to gs saying it was an invalid message            
            log = Log(header="response", message={"header": "Valve data", "status": "Failure", "description": "Unable to find " + valve_type + " in " + valve_location})
            self.enqueue(log, LogPriority.CRIT)
            return Error.REQUEST_ERROR

        _, actuation_type, timestamp = self.registry.get(("valve_actuation", "actuation_type", valve_type, valve_location))
        _, actuation_priority, _ = self.registry.get(("valve", "actuation_priority", valve_type, valve_location))
        log = Log(header="response", message={"header": "Valve data", "status": "Success", "type": valve_type, "location": valve_location, "state": value, "actuation_type": actuation_type, "actuation_priority": actuation_priority, "last_actuated": timestamp})
        self.enqueue(log, LogPriority.INFO)


    def progress(self, stage: Stage):
        #TODO: Determine if the rocket is ready to progress to the next stage
        if True:
            print("Progressing to the next stage")
            self.flag.put(("progress", "stage"), stage)
            self.enqueue(Log("progress", message={"header": "Progress to next stage", "stage": stage, "status": "success"}), LogPriority.CRIT)
        else:
            self.enqueue(Log("response", message={"header": "Progress to next stage", "stage": stage, "status": "failure", "description": "Pi not ready"}), LogPriority.CRIT)

    def test(self, msg: str):
        print("\ntest recieved:", msg)


