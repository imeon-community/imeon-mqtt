import requests
import requests.exceptions
import json
import time, schedule
from paho.mqtt import client as mqtt_client
from datetime import datetime

url_login = "http://10.0.20.201/login"
url_set = "http://10.0.20.201/toRedis"
url = "http://10.0.20.201/"

#mqtt
broker = '10.0.20.240'
port = 1883
sensor_topic    = "imeon/sensor" 
status_topic    = "imeon/status" 
client_id       = "imeon"
username        = "openhabian"
password        = "habianopen"
debug = True



def do_login():
    global s
    payload = {'do_login': 'true',
            'email': 'installer@local',
            'passwd': 'Installer_P4SS'}
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
    #print(r.json())
    if r.json()['val']: print('TRUE')
    else:
        print('FALSE')
    #print(f"Status Code: {r.status_code}, Response: {r.text}")
    #print(f"Status Code: {r.status_code}, Response: {r.json()}")
    decode_values_scan(r.json())
 
    return r.status_code

def do_set_command(command):
    r = s.request("POST", url_set, data={
    'inputdata': command})
    print(f"Set Command: {command} Status Code: {r.status_code}")
    time.sleep(10)
    publish(r.status_code, "command/status")
    return r.status_code

def do_set_time():
    d_date = datetime.now().strftime(("%Y/%m/%d%H:%M"))
    print(d_date)
    r = s.request("POST", url_set, data={'inputdata': 'CDT' + d_date })
    print(f"Time Set Status Code: {r.status_code}")
    return r.status_code

def decode_values_scan(data):
    data1 = data['val'][0]
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
        #print(f'   {v} : {data1[k]}')
        publish(data1[k], v)
    
    publish(data1['pv_input_power1'] + data1['pv_input_power2'], 'inverter_DC_power' )
    publish(data1['pv_input_power2'] - data1['pv_input_power1'], 'inverter_dc_diff' )
    print(f'timestamp local { datetime.now().strftime("%Y/%m/%d %H:%M:%S") }, imeon {data1["time"]}')
    return

def connect_mqtt():
    def on_connect(client, userdata, flags, rc):
        client.subscribe("imeon/command", qos=1)
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
        do_set_command(command)
        

    client = mqtt_client.Client(client_id, clean_session=True, reconnect_on_failure=True )
    client.username_pw_set(username, password)
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
                    print(f"Sent `{msg}` to topic `{topic}`")
                else:
                    print(f"Failed to send message to topic {topic}")
        except Exception as err:
            print("Waiting 5 seconds to reconnect to MQTT server... (" + str(err)+")")
            time.sleep(5)
            continue
        break

def run():
    global payload
    global client
    
    
    schedule.every(30).seconds.do(read_values, opt = 'scan')
    schedule.every().day.at("00:01:01").do(do_set_time) # synchronize inverter time to server time once a day
    
    client = connect_mqtt()
    publish("offline", "status")
    
    while True:
        schedule.run_pending()
        time.sleep(1)
        client.loop()
    

if __name__ == '__main__':
    run()
