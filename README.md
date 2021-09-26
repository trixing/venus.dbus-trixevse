# Venus OS Driver for a custom EV charging station

This program regularly polls a custom EV charging station on
local network and creates a dbus device for an AC charging
station.

This is only useful if you have built a EV charging station
yourself. But it might serve as a useful template for similar
projects.

The source code and hardware plans for the compatible charging
station are going to be published at https://github.com/trixing/trixevse .

The charging station will only show up in the GX remote
control window as no visualization is provided by Victron in
the VRM portal.

## Installation (Supervise)

If you want to run the script on the GX device, proceed like
this 
```
cd /data/
git clone http://github.com/trixing/venus.dbus-trixevse
chmod +x /data/venus.dbus-trixevse/service/run
chmod +x /data/venus.dbus-trixevse/service/log/run
```

If you are on Venus OS < 2.80 you need to also install the
python3 libraries:
```
opkg install python3 python3-requests
```

### Configuration

To configure the service (e.g. provide a fixed IP instead of
the default MDNS name) edit `/data/venus.dbus-trixevse/service/run`.

### Start the service

Finally activate the service
```
ln -s /data/venus.dbus-trixevse/service /service/venus.dbus-trixevse
```


## Possible improvements

- [ ] Show Charging Status in the VRM UI.
