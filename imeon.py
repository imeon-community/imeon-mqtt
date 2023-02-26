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

#create command queue
q_commands = Queue()
q_size = 0

def do_login():
    # do login
    global s
    payload = {'do_login': 'true',
            'email': imeon_email,
            'passwd': imeon_psswd}
    s = requests.session()
    r = s.post(url_login, data=payload)
    print(f"Login Status Code: {r.status_code}, Response: {r.json()}")
    time.sleep(1)
    return r.status_code

def read_values(opt):
    # scan , imeon-status, data
    #client.loop()
    try:
        r = s.get(url + opt)
    except:
        do_login()
        r = s.get(url + opt)
    r.encoding='utf-8-sig'
    print(f"Read Values Status Code: {r.status_code}")
    decode_values_scan(r.json())
 
    return r.status_code

def do_set_time():
    # set time command
    d_date = datetime.now().strftime(("%Y/%m/%d%H:%M"))
    print(d_date)
    r = s.request("POST", url_set, data={'inputdata': 'CDT' + d_date })
    print(f"Time Set Status Code: {r.status_code}")
    return r.status_code

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
            print("connected OK Returned code=",rc)
            client.connected_flag=True #Flag to indicate success
            publish("online", "status")
        else:
            print("Bad connection Returned code=",rc)
            client.bad_connection_flag=True
#            sys.exit(1) #quit
            publish("offline", "status")

    def on_disconnect(client, userdata, flags, rc=0):
        print("DisConnected flags " + str(flags) + " " + str(rc) + str(userdata))
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

def publish(msg, topic):
    # note: topic is constructed imeon/+topic
    topic = "imeon/" + topic
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
    while True:
        if not q_commands.empty():
            command = q_commands.get()
            r = s.request("POST", url_set, data={
                'inputdata': command})
            print(f"Set Command received: {command} Status Code: {r.status_code}")
            publish(command + " - " + str(r.status_code), "command/status")
            q_size = q_commands.qsize()
            print(f"q_size: {q_size}")
        time.sleep(7) # wait for the command to sink in
        

def run():
    global payload
    global client
    
    
    schedule.every().minute.at(":01").do(read_values, opt = 'scan') # read Imeon values every 30 seconds
    schedule.every().minute.at(":31").do(read_values, opt = 'scan') # read Imeon values every 30 seconds
    schedule.every().day.at("00:01:15").do(do_set_time) # synchronize inverter time to server time once a day
    
    client = connect_mqtt()
    publish("offline", "status")
    
    while True:
        schedule.run_pending()
        time.sleep(1)
        client.loop()
    

if __name__ == '__main__':
    daemon = threading.Thread(target=execute_q_command, daemon=True, name="Execute q_commands")
    daemon.start()
    do_login()
    run()
