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

import dbus

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../ext/velib_python'))
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../velib_python'))
from vedbus import VeDbusService

log = logging.getLogger("DbusTrixEVSE")


class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)

def dbusconnection():
    return SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()


class DbusEVSEService:

  def __init__(self, servicename, deviceinstance, ip, name='TrixEVSE', dryrun=False):
    self._dbusservice = VeDbusService(servicename)
    self._name = name
    self._dryrun = dryrun

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

    self._tempservice = self.add_temp_service(deviceinstance, dryrun)
    self._retries = 0

    gobject.timeout_add(5000, self._safe_update)

  def add_temp_service(self, instance, dryrun):

      ds = VeDbusService('com.victronenergy.temperature.trixevse' + ('_dryrun' if dryrun else ''),
                         bus=dbusconnection())
      # Create the management objects, as specified in the ccgx dbus-api document
      ds.add_path('/Mgmt/ProcessName', __file__)
      ds.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
      ds.add_path('/Mgmt/Connection', 'local')

      # Create the mandatory objects
      ds.add_path('/DeviceInstance', instance + (100 if dryrun else 0))
      ds.add_path('/ProductId', 0)
      ds.add_path('/ProductName', 'dbus-trixevse')
      ds.add_path('/FirmwareVersion', 0)
      ds.add_path('/HardwareVersion', 0)
      ds.add_path('/Connected', 1)

      ds.add_path('/CustomName', self._name)
      ds.add_path('/TemperatureType', 2)  # 0=battery, 1=fridge, 2=generic
      ds.add_path('/Temperature', 0)
      ds.add_path('/Status', 0)  # 0=ok, 1=disconnected, 2=short circuit
      return ds

  def _setcurrent(self, path, value):
      try:
        p = requests.post(url = self.CURRENT_URL, data = {'value': value}, timeout=10)
      except Exception as e:
        log.error('Error writing current to station: %s' % e)
        return False
      return True

  def _startstop(self, path, value):
      if value == 0: # stop in victron language
        value = 2 # stop in trix-evse language
      try:
        p = requests.post(url = self.CHARGING_URL, data = {'value': value}, timeout=10)
      except Exception as e:
        log.error('Error writing start/stop to station: %s' % e)
        return False
      return True

  def _safe_update(self):
    try:
        self._update()
        if self._dbusservice['/Connected'] != 1:
            self._dbusservice['/Connected'] = 1
        self._retries = 0
    except Exception as e:
        log.error('Error running update %s' % e)
        if self._dbusservice['/Connected'] != 0:
            self._dbusservice['/Connected'] = 0
            self._tempservice['/CustomName'] = self._name + ' Error'
            self._tempservice['/Temperature'] = -1
        self._retries +=1 
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

    if state == 2:
        power = ds['/Ac/Power']
        self._tempservice['/CustomName'] = self._name + ' Charging [kW]'
        self._tempservice['/Temperature'] = round(power/1000.0, 1)
    elif state == 1:
        self._tempservice['/CustomName'] = self._name + ' Car Connected [A]'
        self._tempservice['/Temperature'] = e['set_current']
    elif not e['charging_enabled']:
        self._tempservice['/CustomName'] = self._name + ' Disabled'
        self._tempservice['/Temperature'] = 0.0
    else:
        self._tempservice['/CustomName'] = self._name + ' Idle [A]'
        self._tempservice['/Temperature'] = e['set_current']

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
  parser.add_argument('--ip', default='trixing-evse.local', help='IP Address of Station')
  parser.add_argument('--service', default='com.victronenergy.evcharger.trixevse', help='Service Name, e.g. for test')
  parser.add_argument('--instance', default=43, help='Instance on DBUS, will be incremented by 100 in dryrun mode')
  parser.add_argument('--dryrun', dest='dryrun', action='store_true')
  parser.add_argument('--name', default='WallBe', help='User visible name of Wallbox')
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

  DbusEVSEService(
    servicename=args.service + ('_dryrun' if args.dryrun else ''),
    deviceinstance=args.instance + (100 if args.dryrun else 0),
    ip=args.ip,
    name=args.name,
    dryrun=args.dryrun)

  logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
  mainloop = gobject.MainLoop()
  mainloop.run()

if __name__ == "__main__":
  main()
