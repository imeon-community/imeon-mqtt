import cProfile
import requests
import requests.exceptions
import json
import time, schedule
from paho.mqtt import client as mqtt_client
from queue import Queue
import threading
from datetime import datetime
from secrets_1 import secrets
  
secret_key = secrets.get('SECRET_KEY')

# imeon to mqqt
# gets values from .../scan page, parses and sends to mqtt channels
# receives commands via mqtt imeon/command channel
# posts result of command to imeon/command/status channel

# retrieve secret credentials
# from secrets.py file 
# see example in secrets copy.py

url_login = secrets.get('URL_LOGIN')
url_set = secrets.get('URL_SET')
url = secrets.get('URL')
url_settings = secrets.get('URL_SETTINGS')

#mqtt settings
broker = secrets.get('BROKER')
port = 1883
client_id       = "imeon"
mqtt_username   = secrets.get('MQTT_USERNAME')
mqtt_password   = secrets.get('MQTT_PASSWORD')
debug = True

#import secrets
imeon_email = secrets.get('IMEON_EMAIL')
imeon_psswd = secrets.get('IMEON_PSSWD')
#imeon_psswd = "Installer_P"
imeon_access_status = False

#create command queue
q_commands = Queue()
q_size = 0

#potentially missing values
BATACH = None
BATADCH = None

def do_login():
    # do login
    global s, imeon_access_status
    while not imeon_access_status:
        payload = {'do_login': 'true',
                'email': imeon_email,
                'passwd': imeon_psswd}
        s = requests.session()
        r = s.post(url_login, data=payload)
        imeon_access_status = r.json()['accessGranted']
        print(f"Login Status Code: {r.status_code}, AccessGranted: {r.json()['accessGranted']}, Response: {r.json()}")
        if imeon_access_status:
            publish("ON", "status/imeon")
        else:
            publish("OFF", "status/imeon")
        if not imeon_access_status: time.sleep(10)
    return imeon_access_status

def read_values(opt):
    # scan , imeon-status, data
    #client.loop()
    try:
        r = s.get(url + opt)
    except Exception as err:
        print("read imeon exception: " + str(err))
        publish("OFF", "status/imeon")
        do_login()
        r = s.get(url + opt)
    else:
        publish("ON", "status/imeon")
    r.encoding='utf-8-sig'
    print(f"Read /{opt} Values Status Code: {r.status_code}")
    if opt=="scan": decode_values_scan(r.json())
    if opt=="data": decode_values_data(r.json())
    #print(f"json: {r.json()}")
    return r.status_code

def do_set_time():
    # set time command
    d_date = datetime.now().strftime(("%Y/%m/%d%H:%M"))
    print(d_date)
    r = s.request("POST", url_set, data={'inputdata': 'CDT' + d_date })
    print(f"Time Set Status Code: {r.status_code}")
    return r.status_code

def decode_values_data(data):
    def transcode(val):
        #transcode values from true/false and 1/0 to ON/OFF
        mapping_table = {
            '1': 'ON',
            '0': 'OFF',
            'true': 'ON',
            'false': 'OFF',
            'True': 'ON',
            'False': 'OFF'
        }
        return mapping_table[str(val)]
    publish(transcode(data['ac_output_enabled']), 'ac_output_enabled')
    publish(transcode(data['enable_status']['charge_bat_with_grid']), 'charge_bat_with_grid')
    publish(transcode(data['enable_status']['discharge_night']), 'discharge_night')
    publish(transcode(data['enable_status']['injection']), 'injection')
    publish(data['max_ac_charging_current'], 'max_ac_charging_current')
    publish(data['mode_name'], 'mode_name')
    publish(data['pv_usage_priority'], 'pv_usage_priority')
    #read value from imeon, if does not exist, use locally stored value
    publish(data.get('max_charging_current', BATACH), 'max_charge_current') 
    publish(data.get('max_discharging_current', BATADCH), 'max_discharge_current')

    discharge_pct = data['discharge_cutoff_pct'].split(" ")
    publish(int(discharge_pct[0]), 'discharge_cutoff_bat')
    publish(int(discharge_pct[1]), 'discharge_cutoff_grid')

def decode_values_scan(data):
    # decode values received from /scan and map them to mqqt channels
    data1 = data['val'][0]
    # mapping of imeon values to channels
    imeon_mapping = {'ac_input_total_active_power': 'inverter_AC_power', 
                        'battery_current': 'battery_current_A', 
                        'battery_soc': 'battery_SOC', 
                        'em_power': 'smart_meter_power',
                        'pv_input_power1': 'inverter_DC1_power', 
                        'pv_input_power2': 'inverter_DC2_power',
                        'ac_output_total_active_power': 'inverter_backup_power_total',
                        'ac_output_power_r': 'inverter_backup_power_L1',
                        'ac_output_active_power_s': 'inverter_backup_power_L2',
                        'ac_output_active_power_t': 'inverter_backup_power_L3',
                        'ac_output_apperent_power_r': 'inverter_backup_apparent_power_L1',
                        'ac_output_apperent_power_s': 'inverter_backup_apparent_power_L2',
                        'ac_output_apperent_power_t': 'inverter_backup_apparent_power_L3',
                        'ac_output_total_apperent_power': 'inverter_backup_apparent_power_total',
                        'ac_output_current': 'inverter_backup_current_L1',
                        'ac_output_current_s': 'inverter_backup_current_L2',
                        'ac_output_current_t': 'inverter_backup_current_L3',
                        'ac_output_voltage': 'inverter_backup_voltage_L1',
                        'ac_output_voltage_s': 'inverter_backup_voltage_L2',
                        'ac_output_voltage_t': 'inverter_backup_voltage_L3'
                    }
    for k,v in imeon_mapping.items():
        # publish values to mqtt
        #print(f'   {v} : {data1[k]}')
        publish(data1[k], v)

    # do some more calculation on the fly and send to communication channels
    publish(data1['pv_input_power1'] + data1['pv_input_power2'], 'inverter_DC_power' ) # sum of both DC strings
    publish(data1['pv_input_power2'] - data1['pv_input_power1'], 'inverter_dc_diff' ) # difference between DC strings, interesting in case you have identical strings, so they should demonstrate same production

    print(f'timestamp local { datetime.now().strftime("%Y/%m/%d %H:%M:%S") }, imeon {data1["time"]}')
    return

def connect_mqtt():
    # connect to mqtt
    def on_connect(client, userdata, flags, rc):
        client.subscribe("imeon/command", qos=1) # subscribe to the channel to receive commands
        print("subscribing to topic imeon/command")
        if rc==0:
            print("mqtt connected OK Returned code=",rc)
            client.connected_flag=True #Flag to indicate success
            publish("ON", "status/mqtt")
        else:
            print("mqtt bad connection Returned code=",rc)
            client.bad_connection_flag=True
#            sys.exit(1) #quit
            publish("OFF", "status/mqtt")

    def on_disconnect(client, userdata, flags, rc=0):
        print("DisConnected flags " + str(flags) + " " + str(rc) + str(userdata))
        publish("OFF", "status/mqtt")
        client.connected_flag=False

    def on_message(client, userdata, message):
        command = str(message.payload.decode("utf-8"))
        print("command received: " , command)
        q_commands.put(command) # put received command on the queue
      

    client = mqtt_client.Client(client_id, clean_session=True, reconnect_on_failure=True )
    client.username_pw_set(mqtt_username, mqtt_password)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message=on_message
    client.connect(broker, port, keepalive=600)
    
    return client

def publish(msg, tpc):
    # note: topic is constructed imeon/+topic
    topic = "imeon/" + tpc
    while True:
        try:
            result = client.publish(topic, msg, qos=0, retain=False)
            status = result[0]
            if debug:
                if status == 0:
                    pass #print(f"Sent `{msg}` to topic `{topic}`")
                else:
                    print(f"Failed to send message to topic {topic}")
        except Exception as err:
            print("Waiting 5 seconds to reconnect to MQTT server... (" + str(err)+")")
            time.sleep(5)
            continue
        break

def execute_q_command():
    #a daemon thread
    #execute commands in sequence q_commands
    #in a separate thread, to make sure that they have separating time period
    #
    # some values may be missing in imeon data response, so we should read them as commands are posted and hold as local variables
    global BATADCH, BATACH
    #endless loop, slow, for imeon to digest commands
    while True:
        if not q_commands.empty():
            command = q_commands.get()

            r = s.request("POST", url_set, data={
                'inputdata': command}) # send the command to imeon
            print(f"Set Command received: {command} Status Code: {r.status_code}")
            publish(command + " - " + str(r.status_code), "command/status")
            q_size = q_commands.qsize()
            print(f"q_size: {q_size}")
            publish(q_size, "command/queue")

            #commands in missing_values will be stored as local variables
            if 'BATADCH' in command: BATADCH = command.split('BATADCH')[1]
            if 'BATACH' in command: BATACH = command.split('BATACH')[1]

        time.sleep(5) # wait for the command to sink in
        read_values('data')
        
def run():
    global payload
    global client
    
    # first start mqtt connection
    client = connect_mqtt()
    
    # login to imeon
    # do_login()
    
    schedule.every().minute.at(":01").do(read_values, opt = 'scan') # read Imeon values every 30 seconds
    schedule.every().minute.at(":31").do(read_values, opt = 'scan') # read Imeon values every 30 seconds
    schedule.every().day.at("00:01:15").do(do_set_time) # synchronize inverter time to server time once a day

    while True:
        schedule.run_pending()
        time.sleep(1)
        client.loop()
    
if __name__ == '__main__':
    daemon = threading.Thread(target=execute_q_command, daemon=True, name="Execute q_commands")
    daemon.start()
    run()
