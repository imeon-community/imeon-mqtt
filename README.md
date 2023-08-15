# imeon-mqqt

## Another version of imeon to mqqt.

Implements reading values of inverter from .../scan and /data page, parses and sends to mqtt channels.

Built for my OPENHAB implementation, but easily adoptable to any service using mqtt.

Receives commands via mqtt imeon/command channel, puts them in queue sends to imeon one by one waiting 5 seconds for command to sink in.
- posts result of command to imeon/command/status channel
- command queue size is posted on imeon/command/queue channel


## Run as a service

to run as a service in linux systemctl, imeon.service is provided
