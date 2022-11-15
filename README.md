# imeon-mqqt

## Another version of imeon to mqqt.

Implements reading values of inverter from .../scan page, parses and sends to mqtt channels

Receives commands via mqtt imeon/command channel
posts result of command to imeon/command/status channel


## Run as a service

to run as a service in linux systemctl, imeon.service is provided
