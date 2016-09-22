#!/usr/bin/python

import bglib, serial, time, datetime, signal, struct, sys, re, optparse, Queue
import threading, Queue, sys
from Queue import Empty
try:
    import json
except ImportError:
    import simplejson as json

q = Queue.Queue()

timer=0
hr=0  

hr_handle=22
htm_handle=16

ble=0

hrm_value =[0x00, 0x00]
htm_value =[0x00,0x00,0x00,0x00,0xff]

connected_devices = []

htm_temp_val=0
sens_val=[]
sens_handle=0

user_val=0
logmode=False

att_handle_measurement = 0
att_handle_measurement_ccc = 0

found_device = False

status=0
device_list=[]

STANDBY = 0
CONNECTING = 1
FINDING_SERVICES = 2
FINDING_ATTRIBUTES = 3
LISTENING_MEASUREMENTS = 4
state = STANDBY


uuid_service = [0x28, 0x00] # 0x2800
uuid_client_characteristic_configuration = [0x29, 0x02] # 0x2902

#uuid for sensor services
uuid_htm_hr_service = [0x18, 0x00] # 0x180D
uuid_htm_hr_characteristic = [0x2a, 0x00] # 0x2A37


# handler for timeout
def my_timeout(sender, args):
	time.sleep(0.5)
	print json.dumps({"type":"bt_debug", "msg": "Timeout!"})

# handler for gap_set_mode response
def my_ble_rsp_gap_set_mode(sender, args):
	time.sleep(0.5)

#used for debug purpose
'''        if(args['result']& 0xFF)!=0x00:
               print json.dumps({"type":"bt_debug", "msg": "Gap_set_mode error:"})
        else:
               print json.dumps({"type":"bt_debug", "msg": "Gap set mode Ok"})
''' 
          
# handler for gap_set_adv_parameters response
def my_ble_rsp_gap_set_adv_parameters(sender, args):
	time.slep(0.5)

#used for debug purpose
'''        if(args['result']& 0xFF)!=0x00:
               print json.dumps({"type":"bt_debug", "msg": "Gap_set_adv error:"})
        else:
               print json.dumps({"type":"bt_debug", "msg": "Gap set adv OK"})
'''

# handler for gap_discover response
def my_ble_rsp_gap_discover(sender, args):
	time.sleep(0.5)

#used for debug purpose
'''        if(args['result']& 0xFF)!=0x00:
               print json.dumps({"type":"bt_debug", "msg": "Gap_set_mode discover error:"})
        else:
               print json.dumps({"type":"bt_debug", "msg": "Gap discover Ok"})
'''

# handler for gap_set_scan response
def my_ble_rsp_gap_set_scan_parameters(sender, args):
	time.sleep(0.5)

#used for debug purpose
'''        if(args['result']& 0xFF)!=0x00:
               print json.dumps({"type":"bt_debug", "msg": "Gap_set_mode scan error:"})
        else:
               print json.dumps({"type":"bt_debug", "msg": "Set scan Ok"})
'''
       
# handler for gap_scan_respons from advertiser
def my_ble_evt_gap_scan_response(sender, args):
    global state, ble, ser, uuid_service, uuid_htm_hr_service, current_mac_addr
    
    #pull UUID from package
    ad_services = []
    this_field = []
    bytes_left = 0
    for b in args['data']:
        if bytes_left == 0:
            bytes_left = b
            this_field = []
        else:
            this_field.append(b)
            bytes_left = bytes_left - 1
            if bytes_left == 0:
                if this_field[0] == 0x02 or this_field[0] == 0x03: #get 16-bit UUID
                    for i in xrange((len(this_field) - 1) / 2):
                        ad_services.append(this_field[-1 - i*2 : -3 - i*2 : -1])

    # look for hr or htm service (official service UUID=0x180D or 0x1809) and if found connect
    
    #print "Debug uuid:", uuid_htm_hr_service #for debug purpose to check uuid
    if uuid_htm_hr_service in ad_services:
        if not args['sender'] in device_list:
            device_list.append(args['sender'])
            
            # connect to device using mac address
            ble.send_command(ser, ble.ble_cmd_gap_connect_direct(current_mac_addr, args['address_type'], 0x20, 0x30, 0x100, 0))
            ble.check_activity(ser, 1)
            state = CONNECTING     
                     
# connection status. collector.
def my_ble_evt_connection_status(sender, args):
        
        global state, ble, ser, status, connection_handle
        if (args['flags'] & 0x05) == 0x05:
                        
                        # connected. look for service
                        connection_handle = args['connection']
                        ble.send_command(ser, ble.ble_cmd_attclient_read_by_group_type(args['connection'], 0x0001, 0xFFFF, list(reversed(uuid_service))))
                        ble.check_activity(ser, 1)
                        state = FINDING_SERVICES

                

# handler for
def my_ble_evt_attclient_group_found(sender, args):
    global ble, ser, att_handle_start, att_handle_end

    # found "service" attribute groups (UUID=0x2800), look for heart rate service
    if args['uuid'] == list(reversed(uuid_htm_hr_service)):

        att_handle_start = args['start']
        att_handle_end = args['end']


# attclient_find_information_found handler
def my_ble_evt_attclient_find_information_found(sender, args):
    global state, ble, ser, att_handle_measurement, att_handle_measurement_ccc
    

    # check for heart rate/health thermometer measurement characteristic
    if args['uuid'] == list(reversed(uuid_htm_hr_characteristic)):
        #print "Found attribute w/UUID=0x%s"%''.join(['%02x' % b for b in uuid_htm_hr_characteristic])
        att_handle_measurement = args['chrhandle']

    # check for subsequent client characteristic configuration
    elif args['uuid'] == list(reversed(uuid_client_characteristic_configuration)) and att_handle_measurement > 0:
        #print "Found attribute w/UUID=0x2902: handle=%d" % args['chrhandle']
        att_handle_measurement_ccc = args['chrhandle']


# attclient_procedure_completed handler
def my_ble_evt_attclient_procedure_completed(sender, args):
    global state, ble, ser, connection_handle, att_handle_start, att_handle_end, att_handle_measurement, att_handle_measurement_ccc, hr, input_json
    

    # check if we just finished searching for services
    if state == FINDING_SERVICES:
        if att_handle_end > 0:
            #print "Found service w/UUID=0x%s"%''.join(['%02x' % b for b in uuid_htm_hr_service])

            # found the Heart Rate service, so now search for the attributes inside
            state = FINDING_ATTRIBUTES
            ble.send_command(ser, ble.ble_cmd_attclient_find_information(connection_handle, att_handle_start, att_handle_end))
            ble.check_activity(ser, 1)
        else:
            print json.dumps({"type":"bt_debug", "msg": "Could not find service "})

    # check if we just finished searching for attributes within the Heart Rate service
    elif state == FINDING_ATTRIBUTES:
        if att_handle_measurement_ccc > 0:
            #print "Found measurement attribute with w/UUID=0x%s"%''.join(['%02x' % b for b in uuid_htm_hr_characteristic])

            # found the measurement + client characteristic configuration, so enable notifications
            # (this is done by writing 0x01 to the client characteristic configuration attribute)
            state = LISTENING_MEASUREMENTS
            if(hr==1):
                ble.send_command(ser, ble.ble_cmd_attclient_attribute_write(connection_handle, att_handle_measurement_ccc, [0x01, 0x00]))
                ble.check_activity(ser, 1)
            else:
                ble.send_command(ser, ble.ble_cmd_attclient_attribute_write(connection_handle, att_handle_measurement_ccc, [0x02, 0x00]))
                ble.check_activity(ser, 1)
                
        else:
            print json.dumps({"type":"bt_debug", "msg": "Could not find  measurement attribute"})

#//////////////////////////////////////////////////////////////////Send Data
def my_ble_evt_attclient_attribute_value(sender, args):
    global state, ble, ser, connection_handle, att_handle_measurement,hr
    
    # check for a new value from the connected device heart rate measurement attribute
    if(hr==1):
    
        if args['connection'] == connection_handle and args['atthandle'] == att_handle_measurement:
            hr_flags = args['value'][0]
            hr_measurement = args['value'][1]
            #print "Heart rate: %d" % (hr_measurement)
	    send_json = {"type":"value", "value": str(hr_measurement), "mac_address":input_json['mac_address']}
	    print json.dumps(send_json)
    else:
        # check for a new value from the connected device temperature measurement attribute
        if args['connection'] == connection_handle and args['atthandle'] == att_handle_measurement:
            
            htm_flags = args['value'][0]
            htm_exponent = args['value'][4]
            htm_mantissa = (args['value'][3] << 16) | (args['value'][2] << 8) | args['value'][1]
        if htm_exponent > 127: # convert to signed 8-bit int
           
            htm_exponent = htm_exponent - 256
            htm_measurement = htm_mantissa * pow(10, htm_exponent)
            temp_type = 'C'
        if htm_flags & 0x01: # value sent is Fahrenheit, not Celsius
            temp_type = 'F'
        if not logmode:
	    time.sleep(0.3)
	    
	    thermo_value = str(htm_measurement) + str(temp_type) #+ str(chr(248)) + str(temp_type)
	    
	    #print "thermo_value is", str(thermo_value)
	    send_json = {"type":"value", "value": str(thermo_value), "mac_address":input_json['mac_address']}
	    print json.dumps(send_json)
        else:
            t = datetime.datetime.now()


# if disconnected. Advertise/scan again. status=1 sensor else collector
def my_ble_evt_connection_disconnected(sender, args):
       global status, ser, ble
       try:
       	      json.dumps({"type":"bt_debug", "msg":str(connected_devices[0])})
       except:
              json.dumps({"type":"bt_debug", "msg":"No more devices connected"})


# start scanning as collector
def start_scan():
        global status, device_list

        device_list=[0]

        status=0
        #print json.dumps({"type":"bt_debug", "msg": "Scanning\n"})
        
        # scan interval 125ms(0.625us x 200), scan window 125ms(0.625us x 200), active scanning(1)
        ble.send_command(ser, ble.ble_cmd_gap_set_scan_parameters(0xC8,0xC8,1))
        ble.check_activity(ser,1)

        # Discover both limited and generic discoverable devices
        ble.send_command(ser, ble.ble_cmd_gap_discover(1))
        ble.check_activity(ser,1)
        
        
# just wait and poll for event/response       
def idle_loop():
	       try:
               	    # wait for event
               	    ble.check_activity(ser)
	       except:
		    hej = ""
	       # hold for cpu load
               time.sleep(0.01)

# menu for user choice
def val():
        global hr, j_uuid
        
        # set service UUID=180d and characteristics UUID=2a37 [heart rate]
        if(j_uuid=='180D'):
              #print json.dumps({"type":"bt_debug", "msg": "Heart Rate"})
              uuid_htm_hr_service[1]=0x0d
              uuid_htm_hr_characteristic[1]=0x37

              hr=1
              start_scan()

        # set service UUID=1809 and characteristics UUID=2a1c [thermometer]     
        elif(j_uuid=='1809'):
              #print json.dumps({"type":"bt_debug", "msg": "Thermometer"})
              uuid_htm_hr_service[1]=0x09
              uuid_htm_hr_characteristic[1]=0x1c

              hr=0
              start_scan()


def converter(): #Convert json objects(strings) to hex values
	global j_uuid, j_mac_addr, current_mac_addr, uuid_htm_hr_service, found_device
	
	#Decode j_uuid to hex, make it a byte array and turn it into a list
	uuid_htm_hr_service = list(bytearray(j_uuid.decode('hex')))
	
	#Remove all '-' from j_mac_addr, decode to hex, make it byte array, reverse it and turn it into a list
	current_mac_addr = list(reversed(bytearray(j_mac_addr.replace('-','').decode('hex'))))
	found_device = True

	val()

def disconnect_devices():
		global connected_devices, j_mac_addr, found_device
	
		n = connected_devices.index(j_mac_addr)
	
		ble.send_command(ser, ble.ble_cmd_connection_disconnect(0))
		ble.check_activity(ser, 1)
	
		connected_devices.remove(j_mac_addr)
		found_device = False
		
		print json.dumps({"type":"bt_debug", "msg":"Disconnected from: "+str(input_json['mac_address'])})
	
def check_input(input):
		global j_uuid, j_mac_addr, connected_devices, input_json
		try:
			input_json = json.loads(input)
		except:
			input_json = {}

		if(input_json['type']=="bt_value"): #check if correct data type received
			j_uuid = input_json['uuid']
			j_mac_addr = input_json['mac_address']
			
			
			#debug check if already connected to device
			if j_mac_addr in connected_devices:
				print "device already exists"
				disconnect_devices()
			
			else:
				print "no device with current mac found"
				connected_devices.append(j_mac_addr)
				converter()
		
		
def get_input():
		#global q
		for line in iter(sys.stdin.readline, ''):
			q.put(line)
		sys.stdin.close()


#loop polling for input on instream
def stdin_poll_loop():
		global connected_devices
		while True:
			time.sleep(0.3)
			try:
				if q.qsize > 0:
					input = q.get_nowait()
					print json.dumps({"type":"bt_debug", "msg":"cought input"})
					
					check_input(input)
			except Empty:
				str = ""
			if len(connected_devices) > 0:
				idle_loop()
		

# initialize and start
def main():
       global hrm_value, ble, ser, htm_temp_val, htm_value,hr
       global j_uuid, j_mac_addr, connected_devices, current_mac_addr, found_device, input_json

       #set up port for use with Raspberry Pi 2
       port_name = "/dev/ttyACM0"
       baud_rate = 115200
       packet_mode = False

       #create BGLib object
       ble = bglib.BGLib()
       ble.packet_mode = packet_mode

       #add handler for BGAPI event
       ble.on_timeout += my_timeout
       ble.ble_evt_connection_status+=my_ble_evt_connection_status
       ble.ble_evt_connection_disconnected+=my_ble_evt_connection_disconnected
       ble.ble_evt_gap_scan_response+=my_ble_evt_gap_scan_response
       ble.ble_evt_attclient_group_found+=my_ble_evt_attclient_group_found
       ble.ble_evt_attclient_find_information_found+=my_ble_evt_attclient_find_information_found
       ble.ble_evt_attclient_procedure_completed+=my_ble_evt_attclient_procedure_completed
       ble.ble_evt_attclient_attribute_value+=my_ble_evt_attclient_attribute_value
       

       # add handler for BGAPI gap response
       ble.ble_rsp_gap_set_mode+=my_ble_rsp_gap_set_mode
       ble.ble_rsp_gap_set_adv_parameters+=my_ble_rsp_gap_set_adv_parameters
       ble.ble_rsp_gap_discover+=my_ble_rsp_gap_discover
       ble.ble_rsp_gap_set_scan_parameters+=my_ble_rsp_gap_set_scan_parameters

       # create serial port object and flush buffers
       ser = serial.Serial(port=port_name, baudrate=baud_rate, timeout=1)
       ser.flushInput()
       ser.flushOutput()


       # disconnect if we are connected already
       ble.send_command(ser, ble.ble_cmd_connection_disconnect(0))
       ble.check_activity(ser, 1)

       # stop advertising if we are advertising already
       ble.send_command(ser, ble.ble_cmd_gap_set_mode(0, 0))
       ble.check_activity(ser, 1)

       # stop scanning if we are scanning already
       ble.send_command(ser, ble.ble_cmd_gap_end_procedure())
       ble.check_activity(ser, 1)
       
       q = Queue.Queue()
	   
       #Set up thread for stdin polling
       t0=threading.Thread(name = 'input-getter', target = get_input)
       t0.daemon = True
       t0.start()
       

       stdin_poll_loop()	   
       
            
#exit program with CTRL+C and "turn off" BLED112 
def ctrl_c_handler(signal, frame):

        # disconnect if we are connected already
        ble.send_command(ser, ble.ble_cmd_connection_disconnect(0))
        ble.check_activity(ser, 1)

        # stop advertising if we are advertising already
        ble.send_command(ser, ble.ble_cmd_gap_set_mode(0, 0))
        ble.check_activity(ser, 1)

        # stop scanning if we are scanning already
        ble.send_command(ser, ble.ble_cmd_gap_end_procedure())
        ble.check_activity(ser, 1)
        exit(0)
signal.signal(signal.SIGINT,ctrl_c_handler)

if __name__ == '__main__':
    main()