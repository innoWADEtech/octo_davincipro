import serial
import struct
import os
import logging
import sys
import json
from io import BytesIO
from threading import Thread, Event
from Queue import Queue
#from .bases import PrinterInterface

log = logging.getLogger(__name__)

class XYZStatusLine(object):
    key = None

    def __init__(self, key, name, description, default=None, subvals=None):
        self.key = key
        self.name = name
        self.description = description
        self.value = default
        self.subvals = subvals
        self.subval_names = []

    @classmethod
    def parse_line(cls, line):
        parts = [s.strip() for s in line.split(":", 1)]
        if len(parts) != 2:
            raise Exception("Bad status line: {}".format(line))
        key, value = parts
        return key, value

    def parse(self, line):
        if not self.subvals:
            self.subval_names = []
            self.value = line
        else:
            nfields = line.count(',')+1
            if isinstance(self.subvals, dict) and nfields in self.subvals:
                self.subval_names = self.subvals[nfields]
            else:
                self.subval_names = self.subvals
            self.value = line.split(",", len(self.subval_names) or None)

    def __str__(self):
        if not self.subval_names:
            return "{description}: {value}".format(**vars(self))
        else:
            s = []
            for n, obj in enumerate(self.value):
                vals = vars(self).copy()
                if n < len(self.subval_names):
                    vals['index'] = self.subval_names[n]
                else:
                    vals['index'] = n
                if vals['index'] is None:
                    continue
                vals['value'] = obj
                s.append("{description} {index}: {value}".format(**vals))
            return "\n".join(s)
        

class XYZStatusLine_s(XYZStatusLine):
    key = "s"

    def parse(self, value):
        data = json.loads(value)
        self.value = data

    def __str__(self):
        lines = []
        for key, value in sorted(self.value.items(), key=lambda p: p[0]):
            flag = bool(value)
            if key == "sd":
                lines.append("SD Card present: {}".format(flag))
            elif key == "eh":
                lines.append("Supports Engraving: {}".format(flag))
            elif key == "dr":
                for drname, dropen in value.items():
                    lines.append("Door open ({}): {}".format(drname, bool(dropen)))
            elif key == "of":
                lines.append("Allows open filament: {}".format(flag))
            elif key == "buzzer":
                lines.append("Buzzer available: {}".format(flag))
            elif key == "fm":
                lines.append("fm value (unknown): {}".format(flag))
            elif key == "fd":
                lines.append("fd value (unknown): {}".format(flag))
        return "\n".join(lines)


class XYZStatusLine_list(XYZStatusLine):
    def parse(self, value):
        parts = value.split(",")
        if parts[0] == "1":
            self.value = parts[1]
            self.subval_names = []
        else:
            self.value = parts
            self.subval_names = range(1, len(parts)+1)

class XYZStatusLine_t(XYZStatusLine_list):
    key = "t"

class XYZStatusLine_w(XYZStatusLine_list):
    key = "w"

class XYZStatusLine_X(XYZStatusLine_list):
    key = "X"

class XYZStatusLine_f(XYZStatusLine_list):
    key = "f"

class XYZStatusLine_O(XYZStatusLine_list):
    key = "O"
    
    def parse(self, value):
        data = json.loads(value)
        self.value = data

    def __str__(self):
        lines = []
        for key, value in sorted(self.value.items(), key=lambda p: p[0]):
            lines.append("Set Temperature {}: {}".format(key, value))
        return "\n".join(lines)
        
class XYZStatusLine_4(XYZStatusLine_list):
    key = "4"
    
    def parse(self, value):
        data = json.loads(value)
        self.value = data

    def __str__(self):
        lines = []
        for key, value in sorted(self.value.items(), key=lambda p: p[0]):
            if key == "wlan":
                for name, num in value.items():
                    lines.append("{}: {}".format(name,num))
        return "\n".join(lines) 
    
class XYZStatus(object):
    Keys = {
        "4": ("ip_address", "IP Address", None),
        "b": ("bed_temperature", "Bed temperature", None),
        "c": ("k_value", "K value", None),
        "d": (
            "job_progress", "Job progress",  None,
            ["percentage", "elapsed time", "estimated time"]
        ),
        "e": ("error_status", "Error status", None),
        "f": (
            "filament_lengths", "Remaining filament", [],
            ["color 1", "color 2"]
        ),
        "i": ("serial_number", "Serial number", None),
        "j": (
            "printer_state", "Printer status", [],
            {
                1: ["status"],
                2: ["status", "substatus"],
            }
        ),
        "L": (
            "lifetimes", "Life left", [],
            {
                3: [None, "machine life", "extruder life"],
                4: [None, "machine life", "extruder life", "last updated"],
            }
        ),
        "n": (
            "system_name", "System name", [],
        ),
        "o": (
            "attributes", "System Attribute", [],
            ["package size (/1024)", "t (unknown)", "c (unknown)", "auto leveling (+/-)"]
        ),
        "O": ("set_temperature", "Set temperature", {}),
        "p": ("model", "Model name", None),
        "s": ("status_flags", "Status flag", []),
        "t": ("extruder_temps", "Extruder temperature", []),
        "v": (
            "os_version", "Versions", None,
            {
                1: ["firmware version"],
                3: ["os version", "app version", "engine version"],
            }
        ),
        "V": ("version", "Version", None),
        "w": ("filament_serials", "Filament serial number", []),
        "h": ("pla_enabled", "PLA enabled", None),
        "k": ("needs_calibration", "Needs calibration (for material type?)", None),
        "W": ("wifi_settings", "Wifi settings", {}),
        "X": ("nozzle_data", "Nozzle information", []),
        "m": ("m_unknown", "m", None),
        "l": ("language", "Language", None),
    }

    def __init__(self):
        self.data = {}
        self.instances = {}
        # Set up lookup dictionary of handlers for each key
        classes = XYZStatusLine.__subclasses__()
        subclss = []
        while classes:
            cls = classes.pop(0)
            subclss.append(cls)
            classes.extend(cls.__subclasses__())
        for key, data in self.Keys.items():
            for c in subclss:
                #print "Checking {} for {}".format(c, key)
                if c.key == key:
                    #print "Selected {}".format(c)
                    subcls = c
                    break
            else:
                subcls = XYZStatusLine
            inst = subcls(key, *data)
            self.instances[key] = inst

    def parse(self, data):
        for line in BytesIO(data).readlines():
            line = line.strip()
            if not line or line == "$":
                continue
            log.debug("Parsing line: {}".format(line))
            key, value = XYZStatusLine.parse_line(line)
            if not key in self.instances:
                log.warning("Unknown status line: {}".format(key))
                continue
            inst = self.instances[key]
            inst.parse(value)
            self.data[inst.name] = self.instances[key]

    def __str__(self):
        lines = []
        for key, status in self.data.items():
            lines.append(str(status))
        return "\n".join(lines)


class ConnectionError(Exception):
    pass

class PrinterError(Exception):
    pass

class SerialConnection(Thread):
    def __init__(self, device, callback=None, drain=False):
        super(SerialConnection, self).__init__()
        self.device = device
        self._drain = drain
        self.ser = None
        self._inq = Queue()
        self.callback = callback
        self.event = Event()
        self.can_send = True

    def __enter__(self):
        self.open()
        if self._drain:
            self.drain()
        return self

    def __exit__(self, exc, msg, tb):
        if exc:
            log.error("Exiting with exception: {} {}".format(exc, msg))
        self.close()

    def run(self):
        log.debug("Starting reader thread")
        try:
            while not self.event.is_set() and self.ser.isOpen():
                log.debug("checking...")
                avail = self.ser.inWaiting()
                log.debug("{} bytes available".format(avail))
                if not avail:
                    log.debug("Sleeping")
                    self.event.wait(0.1)
                else:
                    line = None
                    buf = ""
                    while avail and self.ser.isOpen():
                        log.debug("{} bytes avail".format(avail))
                        try:
                            buf += self.ser.read(avail)
                            log.debug("serial readline gave us: {!r}".format(line))
                            while '\n' in buf:
                                pos = buf.index('\n')+1
                                avail -= pos
                                line = buf[:pos]
                                buf = buf[pos:]
                                log.debug("got line {!r}".format(line))
                                if callable(self.callback):
                                    log.debug("calling callback")
                                    self.callback(line)
                                else:
                                    log.debug("putting {}".format(line))
                                    self._inq.put(line)
                        except Exception as e:
                            log.debug("Serial read failed")
                            line = ""
            log.debug("Exited. Serial: {}, Event: {}".format(self.ser.isOpen(), self.event.is_set()))
        except Exception as e:
            log.exception("Failed to read from serial device")

    def open(self):
        if self.ser:
            self.ser.close()
        #if not os.path.exists(self.device):
           # raise ConnectionError("Device {} not found".format(self.device))
        #elif not stat.S_ISCHR(os.stat(self.device).st_mode):
            #raise ConnectionError("Not a serial device: {}".format(self.device))
        self.ser = serial.serial_for_url(self.device)
        self.ser.baudrate=115200
        self.ser.timeout=2
        self.parity=serial.PARITY_NONE
        self.stopbits=serial.STOPBITS_ONE
        self.bytesize=serial.EIGHTBITS
        if not self.ser.isOpen():
            raise PrinterError("Serial connection to {} failed".format(self.device))
        #self.start()

    def close(self):
        log.debug("Close called")
        self.event.set()
        if self.ser and self.ser.isOpen():
            self.ser.close()

    def drain(self):
        log.debug("Drain...")
        line = None
        while line is None or line:
            line = self.ser.readline()

    def clear(self):
        log.debug("Clearing buffer")
        data = None
        while data is None or data:
            data = self.drain()
            if data:
                log.debug("Cleared line {!r}".format(data))

    def dumpformat(self, string):
        if len(string) > 32:
            #out = self.hexformat(string[:16]) + "..." + self.hexformat(string[-16:])
            out = "{!r}".format(string[:16] + "..." + string[-16:])
        else:
            out = repr(string)
        return out
 
    def write(self, data):
        log.debug(">>> {} bytes".format(len(data)))
        self.ser.write(data)
        self.ser.flush()

    def writeline(self, data):
        self.write(data+"\n")

    def readline(self):
        return self.ser.readline()

    def wait_for_ok(self, expect="ok"):
        log.debug("waiting for ok")
        resp = self.readlines(expect=expect)
        if not resp or resp.strip() != "ok":
            raise Exception("Expected token not found: {}".format(expect))

    def readlines(self, expect=None):
        buf = ""
        line = None
        while line is None or line:
            line = self.readline()
            log.debug("read line {!r}...".format(line))
            if line:
                buf += line
                log.debug("buf is now {!r}".format(buf))
                if line.strip() == expect:
                    log.debug("Token found")
                    break
                elif line.strip() == "E0":
                    return buf
        return buf

class XYZ(object):
    name = "davincipro"
    QueryCmd = "XYZv3/query={}"
    ActionCmd = "XYZv3/action={}"
    ConfigCmd = "XYZv3/config={}"
    UploadCmd = "XYZv3/upload={filename},{size}{option}"
    FirmwareCmd = "XYZv3/firmware={filename},{size}"
    SaveToSD = ",SaveToSD"
    UploadDidFinishCmd = "XYZv3/uploadDidFinish"
    PauseCmd = "print:[pause]"
    ResumeCmd = "print:[resume]"
    CancelCmd = "print:[cancel]"

    def __init__(self, device="/dev/ttyACM0"):
        self.device = device
        self.response = ""
        self.filepos = None
        self.filesize = None
       
    def hexformat(self, string):
        out = "".join("{:x}".format(ord(x)) for x in string)
        return out

          
    def _console_print(self, line):
        sys.stdout.write(line)

    def connect(self, callback=None):
        return SerialConnection(self.device, callback, drain=True)

    def console(self):
        with self.connect(self._console_print) as h:
            line = None
            print "Starting direct console to {}. '.quit' to exit".format(self.device)
            line = raw_input("")
            while line is None or line.strip() != ".quit":
                if line.startswith("\\"):
                    line = line.strip()[1:]
                    h.write(line)
                elif line.startswith("."):
                    line = line.strip()[1:]
                    h.write(line+"\r\n")
                else:
                    h.writeline(line.strip())
                line = raw_input("")

    def parse_status(self, string, raw):
        if not raw:
            status = XYZStatus()
            status.parse(string)
            return str(status)
        else:
            return string
        
    def status(self, raw=False):
        status = self.query_cmd("a", expect="$")
        return self.parse_status(status, raw)

    def action_cmd(self, action):
        with self.connect() as conn:
            return self.generic_cmd(conn, self.ActionCmd, action)

    def generic_cmd(self, conn, template, value):
        cmd = template.format(value)
        return self.bare_cmd(conn, cmd)

    def bare_cmd(self, conn, cmd):
        conn.writeline(cmd)

    def read_response(self, conn, expect):
        log.debug("Reading response...")
        return conn.readlines(expect=expect)

    def query_cmd(self, code, expect=None):
        with self.connect() as conn:
            self.generic_cmd(conn, self.QueryCmd, code)
            return self.read_response(conn, expect)

    def config_cmd(self, value):
        with self.connect() as conn:
            return self.generic_cmd(conn, self.ConfigCmd, value)
            
    def dpr(self, cmd):
        with self.connect() as conn:
            self.bare_cmd(conn, cmd)
            return self.read_response(conn, expect="END")
    
    def dpr_read(self):
        with self.connect() as conn:
            return conn.readline()
            
    def pause(self):
        self.config_cmd(self.PauseCmd)

    def resume(self):
        self.config_cmd(self.ResumeCmd)

    def cancel(self):
        self.config_cmd(self.CancelCmd)

    def _print_reader(self, line):
        if not line.strip().startswith("ok"):
            self._print_continue = True

    def unlock_filament(self):
        self.config_cmd("pda:[1591]")
        self.config_cmd("pdb:[4387]")
        self.config_cmd("pdc:[7264]")
        self.config_cmd("pde:[8046]")

    def write_firmware(self, filename):
        """
        Print the given data or file.
        """
        print "Firmware update disabled - highly experimental!"
        return

        with open(filename, 'rb') as f:
            data = f.read()
            size = os.fstat(f.fileno()).st_size - 16
            header = data[:16]
            body = data[16:]
            model = header.split("+")[0]
            newversion = header.split("+")[1]
        log.info("Writing firmware for model {}, version {}, {} bytes".format(model, newversion, size))
        # Start upload
        with self.connect() as conn:
            cmd = self.FirmwareCmd.format(filename=os.path.basename(filename), size=size)
            cmd += ",Downgrade"
            conn.writeline(cmd)
            conn.wait_for_ok()
            # Send file data
            chunks = (len(body)+8191) / 8192
            blocksize = 8192
            for n in range(0, chunks):
                log.debug("Sending file chunk {}/{}".format(n, chunks))
                chunk = struct.pack(">l", n) + struct.pack(">l", blocksize)
                start = 8192*n
                chunk += body[start:start+8192]
                chunk += "\x00\x00\x00\x00"
                conn.write(chunk)
                # Expect "ok\n"
                conn.wait_for_ok()
            # Send finish; expect no response
            conn.write(self.UploadDidFinishCmd)
            
    def print_data(self, filename, data=None, savetosd=False):
        """
        Print the given data or file.
        """
        if not data and os.path.exists(filename):
            with open(filename, 'rb') as f:
                data = f.read()
                size = os.fstat(f.fileno()).st_size
        else:
            size = len(data)
        # Start upload
        with self.connect() as conn:
            opts = ""
            if savetosd:
                opts = self.SaveToSD
            cmd = self.UploadCmd.format(filename=filename, size=size, option=opts)
            conn.writeline(cmd)
            conn.wait_for_ok()
            # Send file data
            chunks = (len(data)+8191) / 8192
            self.filesize = len(data)+8191
            blocksize = 8192
            for n in range(0, chunks):
                log.debug("Sending file chunk {}/{}".format(n, chunks))
                chunk = struct.pack(">l", n) + struct.pack(">l", blocksize)
                start = 8192*n
                chunk += data[start:start+8192]
                chunk += "\x00\x00\x00\x00"
                conn.write(chunk)
                self.filepos = n*8192
                # Expect "ok\n"
                conn.wait_for_ok()

            # Send finish; expect no response
            conn.write(self.UploadDidFinishCmd)