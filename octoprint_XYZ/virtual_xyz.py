# coding=utf-8
from __future__ import absolute_import, division, print_function
__author__ = "Gina Häußge <osd@foosel.net>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'


import time
import os
import re
import threading
import yaml

try:
    import queue
except ImportError:
    import Queue as queue

from octoprint.settings import settings
from octoprint.plugin import plugin_manager

from . import printers
from . gcode import GCodeFile
from . davinci import ThreeWFile

class VirtualPrinter(object):

    def __init__(self, seriallog_handler=None, read_timeout=5.0, write_timeout=10.0):
        import logging
        self._logger = logging.getLogger(
            "octoprint.plugins.virtual_printer.VirtualPrinter")

        self._seriallog = logging.getLogger(
            "octoprint.plugin.virtual_printer.VirtualPrinter.serial")
        self._seriallog.setLevel(logging.CRITICAL)
        self._seriallog.propagate = False

        if seriallog_handler is not None:
            import logging.handlers
            self._seriallog.addHandler(seriallog_handler)
            self._seriallog.setLevel(logging.INFO)

        self._seriallog.info("-" * 78)
        self._read_timeout = read_timeout
        self._write_timeout = write_timeout
        self.outgoing = queue.Queue()
        self.M28 = False
        self._folder = settings().getBaseFolder('uploads')
        self.www = settings().getBaseFolder("base") + "/www/"
        self._sdCardReady = False
        self._sdPrinter = None
        self._selectedSdFile = None
        self._selectedFile = None
        self._selectedSdFileSize = None
        self._selectedSdFilePos = None
        self._writingToSd = False
        self._writingToSdHandle = None
        self._newSdFilePos = None
        self._heatupThread = None
        self._action_hooks = plugin_manager().get_hooks(
            "octoprint.plugin.virtual_printer.custom_action")
        self._killed = False
        self.filePos = None            
        # XYZ Settings
        self.file3wSize = 0
        self.file3w = None
        self.printer = printers.XYZ()
        self.status = None
        self.connected = self.connect()
        self.printing = False
        
        
    # XYZ Functions
    #XYZ printers availale
    def set_printer(self):
        if self.model == "davincijr":
            return printers.DaVinciJr10()
        elif self.model == "davincipro":
            return printers.DaVinciPro()
        else:
            return
     #If IP address, return socket+address+port or return port           
    def port_parse(self):
        port = settings().get(["plugins", "XYZ", "port"])
        if re.match('[0-9]{1,3}[.][0-9]{1,3}[.][0-9]{1,3}[.][0-9]{1,3}', port):
            port = "socket://" + port + ":9100"
        self.printer.device = port
    #XYZ status update     
    def check_status(self):
        try:
            self.status = yaml.load(self.printer.status())
            self.status['File Position'] = (int(self.status['Job progress percentage']) / 100) * self.file3wSize + 1
            #data = ""
            #data = self.printer.query_cmd("a", expect="$")
            #with open ('/home/sensei/Desktop/XYZv3querya','r') as f:
                #data = f.read() 
        except:
            return
        #self.status = yaml.load(self.printer.parse_status(data,raw=False))
        #self.status['File Position'] = (int(self.status['Job progress percentage']) / 100) * self.file3wSize + 1
     #Check initial connection           
    def connect(self):
        self.port_parse()
        self.check_status()
        if  self.status == None:
            for item in ['No Connection\n', 'port:' + self.printer.device + '\n']:
                self.send (item)
            self.send("// action:disconnect")
            self._killed = True            
            
        else:
            for item in ['Connected\n', self.status['Model name'] + '\n', 'port:' + self.printer.device + '\n']:
                self.send(item)
            settings().set(['plugins', 'XYZ', 'Serial_number'], self.status['Serial number'])
            settings().set(['plugins', 'XYZ', 'Model_name'], self.status['Model name'])
            settings().set(['plugins', 'XYZ', 'Life_extruder'], self.status['Life left extruder life'])
            settings().set(['plugins', 'XYZ', 'Life_machine'], self.status['Life left machine life'])
            settings().set(['plugins', 'XYZ', 'Filament_serial_number'], self.status['Filament serial number'])
            settings().set(['plugins', 'XYZ', 'Version'], self.status['Version'])
            settings().set(['plugins', 'XYZ', 'Firmware'], self.status['Versions firmware version'])
            settings().set(['plugins', 'XYZ', 'Extruder_info'], self.status['Nozzle information 2'])
            settings().set(['plugins', 'XYZ', 'MAC'], self.status['MAC'])
            settings().save()
            return True
 
    def upload(self):
        try:
            #try uploading 3w file to printer
            gcode = settings().get(['plugins','XYZ','gcodeFile'])
            filename = os.path.basename(gcode)
            print (gcode)
            gcoded = GCodeFile.from_file(gcode)
            threeW = ThreeWFile(gcoded)
            file3w = threeW.encrypt()
            self.printer.print_data(filename,data = file3w)
            self.filePos = 1
            self.file3wSize = os.stat(gcode).st_size
            print (self.file3wSize)
        except:
            #except any error and cancel
            self.send("Error Sending File to Print\n")
            self.send("Not SD printing")
            self.sendOk()
            self.printing = False
            self.send("// action:cancel")
            
    def start_print(self):
        #start thread with file upload
        upload = threading.Thread(
            target=self.upload, name="upload")
        upload.start()
        self.printing = True
        test = 0
        #waiting while sending file to printer
        while upload.is_alive():
            fs = self.printer.filesize
            size = self.printer.filepos
            if size > test:
                self.send("Sending" + str(size) + " of " + str(fs))
                self.send('wait')
                test = size
        #waiting while platform homes and printer unresponsive       
#        if self.printing == True:
#            for n in range(0,8):
#                self.send('wait')
#                time.sleep(self._read_timeout)
    #Printing Progress
    def progress(self):
        print ("printing: " + str(self.printing))
        self.check_status()
        print (self.status['Printer status status'])
        if self.status['Printer status status'] == 9501:
            self.send("Heating\n")
            self.send("SD printing byte %d/%d" %
                       (self.status['File Position'], self.file3wSize))
            #self.sendOk()
        elif self.status['Printer status status'] == 9500:
            self.send("Stage Homing\n")
            self.send("SD printing byte %d/%d" %
                       (self.status['File Position'], self.file3wSize))
            #self.sendOk()
        elif self.status['Printer status status'] == 9505:
            self.send("SD printing byte %d/%d" %
                       (self.status['File Position'], self.file3wSize))
            #self.sendOk()
        elif self.status['Printer status status'] == 9508:
            #self.send("SD printing byte %d/%d" %
                       #(self.status['File Position'], self.file3wSize)) 
            self.send("Done printing file\n")
            #self.sendOk()
            self.printing = False
        else:
            self.send("Not SD printing")
    #Temperature
    def temp(self):
        self.check_status()
        print (self.status['Extruder temperature'])
        self.send("ok T:"+ str(self.status['Extruder temperature'])+" B:"+ str(self.status['Bed temperature'])+"\n")    

    def _clearQueue(self, queue):
        try:
            while queue.get(block=False):
                continue
        except queue.Empty:
            pass

    def _kill(self):
        if not self._supportM112:
            return
        self._killed = True
        self.send("echo:EMERGENCY SHUTDOWN DETECTED. KILLED.")

    def list_files(self):
        self.send("Begin file list")
        items = map(
            lambda x: x.upper(),
            os.listdir(self._folder)
            )
        for item in items:
            self.send(item)
        self.send("End file list")
       

    def select_file(self, filename):
        if filename.startswith("/"):
            filename = filename[1:]
        print (self._folder)
        file = os.path.join(self._folder, filename)
        #file = self._folder + filename
        print ("file selected: " + file)
        if not os.path.exists(file) or not os.path.isfile(file):
            self.send("open failed, File: %s." % filename)
        else:
            self._selectedSdFile = file
            self._selectedSdFileSize = os.stat(file).st_size
            print (self._selectedSdFileSize)
            if settings().getBoolean(["devel", "virtualPrinter", "includeFilenameInOpened"]):
                self.send("File opened: %s  Size: %d" %
                           (filename, self._selectedSdFileSize))
            else:
                self.send("File opened")
            self.send("File selected")


    def _setSdPos(self, pos):
        self._newSdFilePos = pos
   
    def _finishSdFile(self):
#        try:
#            self._writingToSdHandle.close()
#        except:
#            pass
#        finally:
#            self._writingToSdHandle = None
#        self._writingToSd = False
#        self._selectedSdFile = None
        self.send("Done saving file")


    def delete_file(self, filename):
        print ("delete: " + filename)
        if filename.startswith("/"):
            filename = filename[1:]
        f = os.path.join(self._folder, filename)
        if os.path.exists(f) and os.path.isfile(f):
            os.remove(f)
            
    #Virtual Printer Input
    def write(self, data):                
            if self.M28 and not "M29" in data:
                self.sendOk()
                return 
            else:    
                try:
                    self.command(data)
                    return data
                except:
                    return 'error'
    
    
    def write_xyz2(self, filename):
        handle =''
        self._writingToSdHandle = handle
        self._writingToSd = True
        time.sleep(0.5)
        self._3WName = settings().get(['plugins','XYZ','gcodeFile'])
        self._selectedFile = self._folder + "/" + self._3WName
        self._selectedSdFile = self._virtualSd +  "/" + (self._3WName.strip(".gcode")).lower() + ".3w"
        print ("write_xyz1:" + self._selectedFile)
        print ("write_xyz2:" + self._selectedSdFile)
        try:
            #main.threedub(["-m"+ self._xyz_name, self._selectedFile, self._selectedSdFile])
            self.send("Writing to file: %s" % self._selectedSdFile)
        except:
            self.send("error writing file")
            self.send("// action:disconnect")
        #self._selectedSdFile = file
        
    #Handle only subset of M Commands for Printer      
    def command(self, data):
        #M105 Temperature Command
        if 'M105' in data:
            self.temp()
        #M110 Start Command   
        elif 'M110' in data:
            self.sendOk()
        #M20 List Virtual SD Card Command    
        elif 'M20' in data:
            if self._sdCardReady:
                self.list_files()
                self.sendOk()
            else:
                self.sendOk()
        #M21 Virtual SD Card Initialize Command        
        elif 'X21' in data:
            self._sdCardReady = True
            self.send("SD card ok")
            self.sendOk()
        #M28 Virtual SD Card File Write Command   
        elif 'M28' in data:
            if self._sdCardReady:
                filename = data.split(None, 1)[1].strip()
                print ("M28: " + filename)
                if ".3w" in filename:
#                   self.send("error writing file")
#                   self.send("// action:disconnect")
#                   self.sendOk()
                    print ("gco")
                else:
                    #self.write_xyz2(filename)
                    self.M28 = True
                    self.send("Writing to file: %s" % filename)
                    self.send("Done saving file")
                    self.sendOk()
        #M29 Virtual SD Card Finish Writing File Command       
        elif 'M29' in data:
            if self._sdCardReady:
                self._finishSdFile()
                self.M28 = False
                self.sendOk()
        #M30 Virtual SD Card Delete File Command       
        elif 'M30' in data:
            if self._sdCardReady:
                filename = data.split(None, 1)[1].strip()
                self.delete_file(filename)
                self.sendOk()
        #M23 Virtual SD Card Select File Command        
        elif 'M23' in data:
            if self._sdCardReady:
                filename = data.split(None, 1)[1].strip()
                self.select_file(filename)
                self.sendOk()
            else:
                self.sendOk()
         #M22 Virtual SD Card Disable Command       
        elif 'M22' in data:
            self._sdCardReady = False
            self.sendOk()
        #M24 XYZ Upload and Print Command    
        elif 'M24' in data:
            if self._sdCardReady == True and self.status['Printer status status'] == 9511:
              self.start_print()
              #self._xyz_printing = True
            elif self._sdCardReady and self.printing:
                self.printer.resume()
        #M27 XYZ Progress Command
        elif 'M27' in data:
            if self._sdCardReady:
                print ("M27")
                #self.send("wait")
                self.progress()
                self.sendOk()
        #M25 XYZ Pause Print Command        
        elif 'M25' in data:
             if self._sdCardReady:
                 self.printer.pause()
                 self.sendOk()
        #M104 Extruder heat 
        elif 'M104' in data:
            if not self.printing:
               self.extruder_heat(data)
            else:
                self.send("error\n")
                self.send("Printing. Can't Change Temperature\n")
                self.sendOk()
        #M140 Extruder heat 
        elif 'M140' in data:
            if not self.printing:
                self.bed_heat(data)
            else:
                self.send("error\n")
                self.send("Printing. Can't Change Temperature\n")
                self.sendOk()
        #Cancel XYZ Cancel Print Command        
        elif 'Cancel' in data:
             if self._sdCardReady:
                 self.printer.cancel()
                 self.sendOk()
        #LED XYZ LED Light Command
        elif 'LED'in data:
            self.dpr_command(data)
            
        else:
            self.sendOk()

    def dpr_command(self, data):
        try:
            response = self.printer.dpr(data)
            if not "ACK" in response:
                self.send("Not Acknowledged\n")
                raise "Not Acknowledged"
            else:
                self.sendOk()
                return
        except:
            self.send("error\n")
            self.sendOk()
            
    def bed_heat(self, data):
        d = re.search(r"(S)([0-9]+)",data)
        temp = int(d.group(2))
        print (temp)
        if temp == 0:
                self.dpr_command("DPRBEH_0")
        elif 1 <= temp <=100:
                self.dpr_command("DPRBEH_"+ str(temp))
                beh = self.status['Bed temperature']
                while beh < temp:
                    self.send("Simulated Temp\n")
                    self.send("ok T:"+ str(self.status['Extruder Temperature']) +" B:"+ str(beh) +"\n")
                    self.send("wait")
                    beh = beh + 2.5
                    time.sleep(5)
        else:
            self.send("Temperature Out of Range")
            self.send("error")
            self.sendOk()
                    
    def extruder_heat(self, data):
         d = re.search(r"(S)([0-9]+)",data)
         temp = int(d.group(2))
         if temp == 0:
             self.dpr_command("DPREXH_1")
         elif 100 <= temp <250:
             self.dpr_command("DPREXH_"+str(temp))
             exh = self.status['Extruder temperature']
             while exh < temp:
                 self.send("Simulated Temp\n")
                 self.send("ok T:"+ str(exh) +" B:"+ str(self.status['Bed temperature'])+"\n")
                 self.send("wait\n")
                 exh = exh + 5
                 time.sleep(5)
         else:
             self.send("Temperature Out of Range")
             self.send("error")
             self.sendOk()
    #Virtual Printer Output       
    def readline(self):
        timeout = self._read_timeout
        try:
		# fetch a line from the queue, wait no longer than timeout
            line = self.outgoing.get(timeout=timeout)
            self._seriallog.info(">>> {}".format(line.strip()))
            self.outgoing.task_done()
            return line
        except queue.Empty:
		# queue empty? return empty line
		return ""
      
    def close(self):
        self._killed = True
        self.incoming = None
        self.outgoing = None
        self.buffered = None
    
    #Ok Output
    def sendOk(self):
        if self.outgoing is None:
            return

        else:
            self.send("ok")

    def sendWaitAfterTimeout(self, timeout=5):
        time.sleep(timeout)
        if self.outgoing is not None:
            self.send("wait")

    def send(self, line):
        if self.outgoing is not None:
            self.outgoing.put(line)

