# coding=utf-8
from __future__ import absolute_import
### (Don't forget to remove me)
# This is a basic skeleton for your plugin's __init__.py. You probably want to adjust the class name of your plugin
# as well as the plugin mixins it's subclassing from. This is really just a basic skeleton to get you started,
# defining your plugin as a template plugin, settings and asset plugin. Feel free to add or remove mixins
# as necessary.
#
# Take a look at the documentation on what other plugin mixins are available.
from octoprint.settings import settings
from octoprint.filemanager.analysis import QueueEntry
import octoprint.plugin
import octoprint.filemanager
import octoprint.filemanager.util
#import shutil
import time
from . davinci import ThreeWFile
import os
import yaml
import flask

class XyzPlugin(octoprint.plugin.StartupPlugin,
                octoprint.plugin.SettingsPlugin,
                octoprint.plugin.AssetPlugin,
                octoprint.plugin.TemplatePlugin,
                octoprint.plugin.EventHandlerPlugin,
                octoprint.plugin.SimpleApiPlugin,
                octoprint.plugin.OctoPrintPlugin):
    
    def __init__(self):
        self.filesdcard = None
                
    def on_after_startup(self):
        self._logger.info("XYZ Plugin Started")
        #Create Empty File for Virtual Port
        path = settings().getBaseFolder("base")
        open(path+'/xyz','w').close()
        settings().set(["serial", "port"],path + "/xyz")
        #settings().set(["serial", "port"],"socket://192.168.0.112:9100")
        settings().set(["serial", "additionalPorts", "-"],path + "/xyz")
        www = path + "/www"
        if not os.path.isdir(www):
            os.makedirs(www)
        #Disable SD card support for cleaner UI since Davinci only allows upload and print
        #Reduce polling of printer since it is slower
        settings().set(["feature","sdSupport"],False)
        settings().set(["feature","sdAlwaysAvailable"],False)
        settings().set(["serial","timeout","sdStatus"],5)
        settings().set(["serial","timeout","temperature"],5)
        settings().set(["serial","timeout","temperatureTargetSet"],10)
        settings().set(["serial","timeout","connection"],15)
        settings().save()
        #Add custom control for LED light
        a = file(settings().getBaseFolder("base") + "/config.yaml",'r')
        b = yaml.load(a)
        davinci = False
        if 'controls' in b:
            for n in b['controls']:
                print n['name']
                if n['name'] == 'DaVinciPro':
                    davinci = True    
        else:
            b['controls']=[]

        if davinci == False:
            b['controls'].append({'children':[{'command':'DPRLED_1','name':'LED ON'},
            {'command':'DPRLED_0','name':'LED OFF'}],'layout':'horizontal','name':'DaVinciPro'})
        c = file(settings().getBaseFolder("base") + "/config.yaml",'w')
        yaml.dump(b,c, default_flow_style=False)
       
    def custom_action_handler(self, comm, line, action, *args, **kwargs):
        #Add custom action cancel to aid cancelling from virtual printer
        if action == "cancel":
            self._printer.cancel_print()
        
    def get_settings_defaults(self):
        #Settings for XYZ Printer
		return dict(
                        port = None,
                        printer = "Not Enabled",
                        gcodeFile = None,
                        Serial_number = None,
                        Model_name = None,
                        Life_extruder = None,
                        Life_machine = None,
                        Filament_serial_number = None,
                        Version = None,
                        Firmware = None,
                        Extruder_info = None,
                        MAC = None,                                              
                        )
	
    def get_api_commands(self):
        return dict(
        printXYZ=["filename"],
        )
        
    def on_api_command(self, command, data):
        #Override Print Command so can set as SD card then convert to .3w and print     
        if command == "printXYZ":
            print(data['filename'])
            printer = self._printer.get_current_connection()
            if printer[1] == settings().getBaseFolder("base") + "/xyz":
                self._printer.commands("X21")
                filegcode = settings().getBaseFolder("uploads") + "/" + data['filename']
                settings().set(["plugins","XYZ","gcodeFile"],filegcode)
                settings().save()
                self._file_manager.get_metadata("local","/"+ data['filename'])
                self._printer.select_file(data['filename'],True, True)
                
    def on_api_get(self, request):
        return flask.jsonify(foo="bar")

    def get_template_configs(self):
        return [
        dict(type="settings", custom_bindings=False)
        ]    
    
    def get_assets(self):
        return dict(
		js=["js/XYZ.js"],
		css=["css/XYZ.css"],
		ess=["less/XYZ.less"]
		)
  
    def on_event(self,event,payload):
#Delete .3w file
        if event == "Upload" and ".3w" in payload['file']:
            www = settings().getBaseFolder("uploads")+ "/" + payload['file']
            self._file_manager.remove_file("local", www)
        
#Check if Print Done. Add History to Gcode File. Disable SdCard.              
        if event == "PrintDone" and payload['origin'] == "sdcard":
            printer = self._printer.get_current_connection()
            if printer[1] == settings().getBaseFolder("base") + "/xyz":               
                filegcode = settings().getBaseFolder("uploads") + "/" + payload['filename']
                filename = os.path.basename(filegcode)
                gcodepath = os.path.dirname(filegcode)
                a = file(gcodepath + "/.metadata.yaml",'r')
                b = yaml.load(a)
                if not 'history' in b[filename]:
                    b[filename]['history'] = []
                b[filename]['history'].append({'timestamp': time.time(), 'printTime': payload['time'], 'printerProfile': printer[3]['id'], 'success': True})
                avg = 0
                n = 0
                for x in b[filename]['history']:
                    if x['printTime']:
                        n = n + 1
                        avg = avg + x['printTime']
                avg = avg / n
                b[filename]['statistics'] = {'averagePrintTime': avg, 'lastPrintTime': payload['time']}
                c = file(gcodepath + "/.metadata.yaml",'w')
                yaml.dump(b,c, default_flow_style=False)
                self._printer.commands("M22")
#Check if Print Cancelled. Add History to Gcode File. Disable SdCard. Remove .3w file.                
        elif event == "PrintCancelled" or event == "PrintFailed":
            print ("Cancelled")
            printer = self._printer.get_current_connection()
            if printer[1] == settings().getBaseFolder("base") + "/xyz":
                self._printer.commands("Cancel")
                filegcode = settings().getBaseFolder("uploads") + "/" + payload['filename']
                filename = os.path.basename(filegcode)
                gcodepath = os.path.dirname(filegcode)
                a = file(gcodepath + "/.metadata.yaml",'r')
                b = yaml.load(a)
                if not 'history' in b[filename]:
                    b[filename]['history'] = []
                b[filename]['history'].append({'timestamp': time.time(), 'printerProfile': printer[3]['id'],'success': False})
                c = file(gcodepath + "/.metadata.yaml",'w')
                yaml.dump(b,c, default_flow_style=False)
                self._printer.commands("M22")

#Check if Virtual XYZ Printer Port Selected. Return Virtual XYZ Printer                
    def serial_factory(self, comm_instance, port, baudrate,
    	                            read_timeout):
                                  
            if not port == settings().getBaseFolder("base")+"/xyz":
    			return None
                            
            import logging.handlers 
            from octoprint.logging.handlers import CleaningTimedRotatingFileHandler
    
            seriallog_handler = CleaningTimedRotatingFileHandler(self._settings.get_plugin_logfile_path(postfix="serial"),
    		                                                     when="D",
    		                                                     backupCount=3)
            seriallog_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            seriallog_handler.setLevel(logging.DEBUG)
            from . import virtual_xyz
    
            serial_obj = virtual_xyz.VirtualPrinter(seriallog_handler=None,
    		                                    read_timeout=float(read_timeout))
            return serial_obj   
#Add .3w file
    def threedub(self, *args, **kwargs):
            return dict(
                machinecode = dict(
                 www = ["3W", "3w"]
                                )
                        )
#Decode 3W file and send gcode file for xyz header                        
    def hook(self, path, file_object, printer_profile=None, links=None, allow_overwrite=True, *args, **kwargs):
        printer = settings().get(['plugins','XYZ','printer'])
        if printer == 'Not Enabled':
            return file_object
        if ".3w" in file_object.filename:
            gcode = path.strip(".3w") + ".gcode"
            print (gcode)
            decode = ThreeWFile.from_file(file_object.path)
            decoded = decode.gcode
            decoded.write(gcode)
        else:
            gcode = path
        xyz = self._printer_profile_manager.get("_default")
        name = os.path.basename(gcode)
        entry = QueueEntry(name,gcode,"gcode","local",gcode, xyz)
        self._analysis_queue.register_finish_callback(self.xyz_header)
        self._analysis_queue.enqueue(entry,high_priority=True) 
        return 
#remove comments, replace G0 with G1, and add xyz header    
    def xyz_header(self,entry, analysis):
        name = str(entry).strip("local:")
        name = os.path.basename(name)
        header_template = """\
; filename = {filename}
; print_time = {time}
; machine = {machine}
; total_layers = {layers}
; version = 17032409
; total_filament = {filament}
; nozzle_diameter = 0.40
; layer_height = 0.20
; support_material = 0
; support_material_extruder = 1
; extruder_filament = {filament}:0.00
; extruder = 1
; temperature = 195
; bed_temperature = 50
; non_double_speed = 1
; filamentid = 50,50,
; materialid = 0,
; fill_density = 0.20
; raft_layers = 0
; support_density = 0.15
; shells = 2
; speed = 30
; brim_width = 0
; dimension = {X}:{Y}:{Z}
; top_solid_layers = 3
; bottom_solid_layers = 3
; fill_pattern = rectilinear
; perimeter_speed = 30
; external_perimeter_speed = 30
; small_perimeter_speed = 30
; top_solid_infill_speed = 30
; solid_infill_speed = 30
; bridge_speed = 20
; travel_speed = 45
; retract_speed = 40
; retract_length = 6
; retract_before_travel = 2
; retract_lift = 0
; retract_restart_extra = 0
; retract_layer_change = 1
; only_retract_when_crossing_perimeters = 1
; first_layer_speed = 20
; extrusion_multiplier_perimeter = 1
; extrusion_multiplier_infill = 1
; Call_From_APP = XYZware Pro 1.1.15.1
; speed_limit_open = 0
; Total computing time = 0 sec.
; threads = 1
M107
M108
"""
        footer = "M107\n"
        with open (settings().getBaseFolder("uploads") +"/" + name,'r') as f:
                data = f.read()
        code = []
        layers = 0
        lines = data.split('\n')
        for line in lines:
            if line.startswith(";"):
                continue
            elif line.startswith("G0"):
                line = line.replace("G0","G1")
            elif line.startswith("M107"):
                continue
            elif line.startswith("M108"):
                continue
            elif line.startswith(" "):
                continue
            elif "Z" in line:
                layers = layers + 1
            code.append(line + '\n')
        coded = ''.join(code)
        
        meta = {}
        meta['filename'] = name
        meta['time'] = analysis['estimatedPrintTime']
        meta['machine'] = settings().get(['plugins','XYZ','printer'])
        meta['layers'] = layers
        meta['X'] = analysis['dimensions']['width']
        meta['Y'] = analysis['dimensions']['depth']
        meta['Z'] = analysis['dimensions']['height']
        meta['filament'] = analysis['filament']['tool0']['length']
        #meta['Extruder_info'] = settings().get(['plugins','XYZ','Extruder_info'])
        header = header_template.format(**meta)        
        
        gcode = header + coded + footer
        with open (settings().getBaseFolder("uploads") +"/" + name, 'w') as f:
                f.write(gcode)
        
	##~~ Softwareupdate hook

#	def get_update_information(self):
		# Define the configuration for your plugin to use with the Software Update
		# Plugin here. See https://github.com/foosel/OctoPrint/wiki/Plugin:-Software-Update
		# for details.
#		return dict(
#			XYZ=dict(
#				displayName="Xyz Plugin",
#				displayVersion=self._plugin_version,

				# version check: github repository
#				type="github_release",
#				user="you",
#				repo="OctoPrint-Xyz",
#				current=self._plugin_version,

				# update method: pip
#				pip="https://github.com/you/OctoPrint-Xyz/archive/{target_version}.zip"
#			)
#		)


# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "Xyz Plugin"

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = XyzPlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
            "octoprint.comm.transport.serial.factory": __plugin_implementation__.serial_factory,
#		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
            "octoprint.comm.protocol.action":  __plugin_implementation__.custom_action_handler,
            "octoprint.filemanager.extension_tree": __plugin_implementation__.threedub,
            "octoprint.filemanager.preprocessor": __plugin_implementation__.hook
	}

