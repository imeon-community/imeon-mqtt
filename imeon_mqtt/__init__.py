import asyncio
import requests
from datetime import datetime
from aiomqtt import Client, MqttError
import queue
import json, sys, os, pprint, logging
from dotenv import load_dotenv
from pathlib import Path
import signal

logging.basicConfig(level=logging.INFO)

# import secrets
load_dotenv()

URL_LOGIN = os.getenv('URL_LOGIN')
URL_SET = os.getenv('URL_SET')
URL = os.getenv('URL')
URL_SETTINGS = os.getenv('URL_SETTINGS')

BROKER = os.getenv('BROKER')
PORT = 1883
CLIENT_ID       = "imeon"
MQTT_USERNAME   = os.getenv('MQTT_USERNAME')
MQTT_PASSWORD   = os.getenv('MQTT_PASSWORD')

IMEON_EMAIL = os.getenv('IMEON_EMAIL')
IMEON_PSSWD = os.getenv('IMEON_PSSWD')

MQTT_ROOT_TOPIC = "imeon/"
MQTT_COMMAND_TOPIC = "imeon/command"


imeon_access_status = False
mqqt_client = None

#potentially missing values
BATACH = None
BATADCH = None

async def do_login():
    # do login
    global s, imeon_access_status
    while not imeon_access_status:
        payload = {'do_login': 'true',
                'email': IMEON_EMAIL,
                'passwd': IMEON_PSSWD}
        s = requests.session()
        r = s.post(URL_LOGIN, data=payload)
        imeon_access_status = r.json()['accessGranted']
        logging.info("Login succesfull")
        logging.info("Login Status Code %s, AccessGranted: %s, Response: %s", r.status_code, r.json()['accessGranted'], r.json())
        if imeon_access_status:
            await publish("ON", "status/imeon")
        else:
            await publish("OFF", "status/imeon")
        if not imeon_access_status: asyncio.sleep(10)
    return imeon_access_status

async def read_values(opt):
    # opt: scan , imeon-status, data
    #client.loop()
    if 's' not in globals(): 
        await do_login()
    status = 0
    while status!=200:
        try:
            r = s.get(URL + opt)
            r.raise_for_status()
            status = r.status_code
        except Exception as err:
            s.close()
            logging.error("read imeon exception: " + str(err))
            await publish("OFF", "status/imeon")
            asyncio.sleep(5)
            do_login()
        else:
            await publish("ON", "status/imeon")
        
    
    r.encoding='utf-8-sig'
    logging.debug(f"Read /{opt} -- values Status Code: {r.status_code}")
    if opt=="scan": await decode_values_scan(r.json())
    if opt=="data": await decode_values_data(r.json())
    logging.debug(f"json: {r.json()}")
    return r.status_code

async def do_set_time():
    # set time command
    d_date = datetime.now().strftime(("%Y/%m/%d%H:%M"))
    r = s.request("POST", URL_SET, data={'inputdata': 'CDT' + d_date })
    logging.info(f"Time Set Status Code: {r.status_code}")
    return r.status_code

async def decode_values_data(data):
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
    await publish(transcode(data['ac_output_enabled']), 'ac_output_enabled')
    await publish(transcode(data['enable_status']['charge_bat_with_grid']), 'charge_bat_with_grid')
    await publish(transcode(data['enable_status']['discharge_night']), 'discharge_night')
    await publish(transcode(data['enable_status']['injection']), 'injection')
    await publish(data['max_ac_charging_current'], 'max_ac_charging_current')
    await publish(data['mode_name'], 'mode_name')
    await publish(data['pv_usage_priority'], 'pv_usage_priority')
    #read value from imeon, if does not exist, use locally stored value
    await publish(data.get('max_charging_current', BATACH), 'max_charge_current') 
    await publish(data.get('max_discharging_current', BATADCH), 'max_discharge_current')

    discharge_pct = data['discharge_cutoff_pct'].split(" ")
    await publish(int(discharge_pct[0]), 'discharge_cutoff_bat')
    await publish(int(discharge_pct[1]), 'discharge_cutoff_grid')

async def decode_values_scan(data):
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
        await publish(data1[k], v)

    # do some more calculation on the fly and send to communication channels
    await publish(data1['pv_input_power1'] + data1['pv_input_power2'], 'inverter_DC_power' ) # sum of both DC strings
    await publish(data1['pv_input_power2'] - data1['pv_input_power1'], 'inverter_dc_diff' ) # difference between DC strings, interesting in case you have identical strings, so they should demonstrate same production

    logging.info(f'IMEON scan timestamp local { datetime.now().strftime("%Y/%m/%d %H:%M:%S") }, imeon {data1["time"]}')
    return

async def publish(msg, tpc):
    global mqtt_client
    # print(f"PUBLISH {tpc} : {msg}") # for debugging
    if not msg: return #do not publish  empty messages

    # note: topic is constructed imeon/+topicmaps
    topic = MQTT_ROOT_TOPIC + tpc
    await mqtt_client.publish(topic, payload=msg)
    

async def execute_commands(work_queue):
    # some values may be missing in imeon data response, so we should read them as commands are posted and hold as local variables
    global BATADCH, BATACH, s
    # when mqtt listene puts commands to the queue, execute commands and let  5 seconds to sink in

    while True:
        command = await work_queue.get()
        logging.info(f"Queued command {command} ")
        #execute commands in sequence q_commands
    
        r = s.request("POST", URL_SET, data={
            'inputdata': command}) # send the command to imeon
        logging.info(f"Command sent to Imeon: {command} Status Code: {r.status_code}")
        await publish(command + " - " + str(r.status_code), "command/status")
        q_size = work_queue.qsize()
        logging.info(f"q_size: {q_size}")
        await publish(q_size, "command/queue")

        #commands in missing_values will be stored as local variables
        # so they will be published back to mqtt (if no values retrieved from json)
        if 'BATADCH' in command: BATADCH = command.split('BATADCH')[1]
        if 'BATACH' in command: BATACH = command.split('BATACH')[1]
        work_queue.task_done()
        await asyncio.sleep(5) # delay for command to sink in to inverter

        await read_values('data')

async def read_imeon_values_task(opt):
    # read imeon values every 30 seconds
    while True:
        await read_values(opt)
        await asyncio.sleep(30)

async def set_imeon_time_task():
    # set imeon time once per day
    while True:
        await do_set_time()
        await asyncio.sleep(60*60*24) 

async def main():
    global mqtt_client
    
    mqtt_client = Client(hostname=BROKER,port=PORT,username=MQTT_USERNAME,password=MQTT_PASSWORD)
    
        
    q_commands = asyncio.Queue() # create command queue, which executes received commands
    
    q_task = asyncio.create_task(execute_commands(q_commands)) # create a perpetual task for execution of commands
    read_task = asyncio.create_task(read_imeon_values_task('scan')) 
    set_time_task = asyncio.create_task(set_imeon_time_task())
    
    

    # listen to mqtt messages and put them to q_commands queue for execution
    # recconect if lost
    interval = 5  # Seconds
    while True:
        try:
            async with mqtt_client:
                async with mqtt_client.messages() as messages:
                    await mqtt_client.subscribe(MQTT_COMMAND_TOPIC)
                    async for message in messages:
                        msg = str(message.payload.decode("utf-8"))
                        await q_commands.put(msg)
        except MqttError:
            logging.error(f"Connection lost; Reconnecting in {interval} seconds ...")
            await asyncio.sleep(interval)


# Change to the "Selector" event loop if platform is Windows
if sys.platform.lower() == "win32" or os.name.lower() == "nt":
    from asyncio import set_event_loop_policy, WindowsSelectorEventLoopPolicy
    set_event_loop_policy(WindowsSelectorEventLoopPolicy())
# Run your async application as usual

if __name__ == "__main__":
    asyncio.run(main())