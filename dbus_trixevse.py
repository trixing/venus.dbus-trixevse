#!/usr/bin/env python

"""
Created by Jan Dittmer <jdi@l4x.org> in 2021

Losely Based on DbusDummyService and RalfZim/venus.dbus-fronius-smartmeter

To set new current:

dbus -y com.victronenergy.evcharger.trixevse "/SetCurrent" SetValue 7

"""
try:
  import gobject
except ImportError:
  from gi.repository import GLib as gobject
import argparse
import platform
import logging
import sys
import os
import requests # for http GET
try:
    import thread   # for daemon = True
except ImportError:
    pass

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../ext/velib_python'))
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../velib_python'))
from vedbus import VeDbusService

log = logging.getLogger("DbusTrixEVSE")

class DbusEVSEService:

  def __init__(self, servicename, deviceinstance, ip):
    self._dbusservice = VeDbusService(servicename)

    url = 'http://' + ip
    self.URL = url + '/j'
    self.CURRENT_URL = url + '/current'
    self.CHARGING_URL = url + '/charging'


    paths=[
      '/Ac/Power',
      '/Ac/L1/Power',
      '/Ac/L2/Power',
      '/Ac/L3/Power',
      '/Ac/Energy/Forward',
      '/Ac/Frequency',
      '/Ac/Voltage',
      '/Status',
      '/Current',
      '/MaxCurrent',
      '/Mode',
      '/ChargingTime'
    ]

    logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

    # Create the management objects, as specified in the ccgx dbus-api document
    self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
    self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
    self._dbusservice.add_path('/Mgmt/Connection', ip)

    # Create the mandatory objects
    self._dbusservice.add_path('/DeviceInstance', deviceinstance)
    self._dbusservice.add_path('/ProductId', 16) # value used in ac_sensor_bridge.cpp of dbus-cgwacs
    self._dbusservice.add_path('/ProductName', 'Trixing EVSE')
    self._dbusservice.add_path('/FirmwareVersion', 0.1)
    self._dbusservice.add_path('/HardwareVersion', 0)
    self._dbusservice.add_path('/Connected', 0)

    self._dbusservice.add_path(
        '/SetCurrent', None, writeable=True, onchangecallback=self._setcurrent)
    self._dbusservice.add_path(
        '/StartStop', None, writeable=True, onchangecallback=self._startstop)

    for path in paths:
      self._dbusservice.add_path(path, None)

    self._retries = 0

    gobject.timeout_add(5000, self._safe_update)

  def _setcurrent(self, path, value):
      p = requests.post(url = self.CURRENT_URL, data = {'value': value}, timeout=10)
      return True

  def _startstop(self, path, value):
      if value == 0: # stop in victron language
        value = 2 # stop in trix-evse language
      p = requests.post(url = self.CHARGING_URL, data = {'value': value}, timeout=10)
      return True

  def _safe_update(self):
    try:
        self._update()
        if self._retries > 1:
            self._dbusservice['/Connected'] = 1
        self._retries = 0
    except Exception as e:
        log.error('Error running update %s' % e)
        self._retries +=1 
        if self._retries > 1:
            self._dbusservice['/Connected'] = 0
    return True

  def _update(self):
    r = requests.get(url = self.URL, timeout=10)
    d = r.json() 
    m = d['meter']
    e = d['evse']
    c = d['charge']
    ds = self._dbusservice
    if e['phases'] == 1:
        ds['/Ac/L1/Power'] = float(m['power'])
        ds['/Ac/L2/Power'] = 0.0
        ds['/Ac/L3/Power'] = 0.0
    elif e['phases'] == 3:
        ds['/Ac/L1/Power'] = float(m['power'])/3
        ds['/Ac/L2/Power'] = float(m['power'])/3
        ds['/Ac/L3/Power'] = float(m['power'])/3
    ds['/Ac/Power'] = float(m['power'])
    ds['/Ac/Frequency'] = m['frequency']
    ds['/Ac/Voltage'] = m['voltage']
    ds['/Current'] = m['current']
    ds['/SetCurrent'] = e['set_current']
    ds['/MaxCurrent'] = 20
    ds['/Ac/Energy/Forward'] = float(m['energy_import'])
    ds['/ChargingTime'] = c['duration']
    if e['charging_enabled']:
        ds['/StartStop'] =  1
    else:
        ds['/StartStop'] =  0

    if e['mode'] == 2:
        ds['/Mode'] = 1 # Auto
    else:
        ds['/Mode'] = 0 # Manual

    state = 0 # disconnected
    if e['vehicle_present'] == True:
        state = 1 # connected
        if e['charging'] == True:
            state = 2 # charging
    ds['/Status'] = state
    log.info("Car Consumption: %s, State: %s" % (ds['/Ac/Power'], ds['/Status']))
    return d


def main():
  #logging.basicConfig(level=logging.INFO)

  root = logging.getLogger()
  root.setLevel(logging.INFO)

  handler = logging.StreamHandler(sys.stdout)
  handler.setLevel(logging.INFO)
  formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
  handler.setFormatter(formatter)
  root.addHandler(handler)

  log.info('Startup')
  parser = argparse.ArgumentParser()
  parser.add_argument('--ip', help='IP Address of Station')
  parser.add_argument('--service', help='Service Name, e.g. for test')
  args = parser.parse_args()
  if args.ip:
      log.info('User supplied IP: %s' % args.ip)
  else:
      log.info('IP not supplied')
      sys.exit(1)


  try:
    thread.daemon = True # allow the program to quit
  except NameError:
    pass

  from dbus.mainloop.glib import DBusGMainLoop
  # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
  DBusGMainLoop(set_as_default=True)

  pvac_output = DbusEVSEService(
    servicename=args.service or 'com.victronenergy.evcharger.trixevse',
    deviceinstance=43,
    ip=args.ip)

  logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
  mainloop = gobject.MainLoop()
  mainloop.run()

if __name__ == "__main__":
  main()
