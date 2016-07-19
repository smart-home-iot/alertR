#!/usr/bin/python2

# written by sqall
# twitter: https://twitter.com/sqall01
# blog: http://blog.h4des.org
# github: https://github.com/sqall01
#
# Licensed under the GNU Public License, version 2.

import sys
import os
from lib import ServerCommunication, ConnectionWatchdog
from lib import SMTPAlert
from lib import WundergroundDataCollector, WundergroundTempPollingSensor, \
	WundergroundHumidityPollingSensor, WundergroundForecastTempPollingSensor, \
	WundergroundForecastRainPollingSensor, SensorExecuter
from lib import UpdateChecker
from lib import GlobalData
import logging
import time
import socket
import random
import xml.etree.ElementTree


# Function creates a path location for the given user input.
def makePath(inputLocation):
	# Do nothing if the given location is an absolute path.
	if inputLocation[0] == "/":
		return inputLocation
	# Replace ~ with the home directory.
	elif inputLocation[0] == "~":
		return os.environ["HOME"] + inputLocation[1:]
	# Assume we have a given relative path.
	return os.path.dirname(os.path.abspath(__file__)) + "/" + inputLocation


if __name__ == '__main__':

	# generate object of the global needed data
	globalData = GlobalData()

	# Create sensor data collector thread.
	sensorDataCollector = WundergroundDataCollector(globalData)

	fileName = os.path.basename(__file__)

	# parse config file, get logfile configurations
	# and initialize logging
	try:
		configRoot = xml.etree.ElementTree.parse(
			globalData.configFile).getroot()

		logfile = makePath(
			str(configRoot.find("general").find("log").attrib["file"]))

		# parse chosen log level
		tempLoglevel = str(
			configRoot.find("general").find("log").attrib["level"])
		tempLoglevel = tempLoglevel.upper()
		if tempLoglevel == "DEBUG":
			loglevel = logging.DEBUG
		elif tempLoglevel == "INFO":
			loglevel = logging.INFO
		elif tempLoglevel == "WARNING":
			loglevel = logging.WARNING
		elif tempLoglevel == "ERROR":
			loglevel = logging.ERROR
		elif tempLoglevel == "CRITICAL":
			loglevel = logging.CRITICAL
		else:
			raise ValueError("No valid log level in config file.")

		# initialize logging
		logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s',
			datefmt='%m/%d/%Y %H:%M:%S', filename=logfile,
			level=loglevel)

	except Exception as e:
		print "Config could not be parsed."
		print e
		sys.exit(1)

	# parse the rest of the config with initialized logging
	try:

		# check if config and client version are compatible
		version = float(configRoot.attrib["version"])
		if version != globalData.version:
			raise ValueError("Config version '%.3f' not "
				% version
				+ "compatible with client version '%.3f'."
				% globalData.version)

		# parse server configurations
		server = str(configRoot.find("general").find("server").attrib["host"])
		serverPort = int(
			configRoot.find("general").find("server").attrib["port"])

		# get server certificate file and check if it does exist
		serverCAFile = os.path.abspath(makePath(
			str(configRoot.find("general").find("server").attrib["caFile"])))
		if os.path.exists(serverCAFile) is False:
			raise ValueError("Server CA does not exist.")

		# get client certificate and keyfile (if required)
		certificateRequired = (str(
			configRoot.find("general").find("client").attrib[
			"certificateRequired"]).upper()	== "TRUE")

		if certificateRequired is True:
			clientCertFile = os.path.abspath(makePath(str(
			configRoot.find("general").find("client").attrib["certFile"])))
			clientKeyFile = os.path.abspath(makePath(str(
			configRoot.find("general").find("client").attrib["keyFile"])))
			if (os.path.exists(clientCertFile) is False
				or os.path.exists(clientKeyFile) is False):
				raise ValueError("Client certificate or key does not exist.")
		else:
			clientCertFile = None
			clientKeyFile = None

		# get user credentials
		username = str(
			configRoot.find("general").find("credentials").attrib["username"])
		password = str(
			configRoot.find("general").find("credentials").attrib["password"])

		# Set connection settings.
		globalData.persistent = 1 # Consider sensor client always persistent

		# parse smtp options if activated
		smtpActivated = (str(
			configRoot.find("smtp").find("general").attrib[
			"activated"]).upper() == "TRUE")
		if smtpActivated is True:
			smtpServer = str(
				configRoot.find("smtp").find("server").attrib["host"])
			smtpPort = int(
				configRoot.find("smtp").find("server").attrib["port"])
			smtpFromAddr = str(
				configRoot.find("smtp").find("general").attrib["fromAddr"])
			smtpToAddr = str(
				configRoot.find("smtp").find("general").attrib["toAddr"])

		# parse update options
		updateActivated = (str(
			configRoot.find("update").find("general").attrib[
			"activated"]).upper() == "TRUE")
		if updateActivated is True:
			updateServer = str(
				configRoot.find("update").find("server").attrib["host"])
			updatePort = int(
				configRoot.find("update").find("server").attrib["port"])
			updateLocation = str(
				configRoot.find("update").find("server").attrib["location"])
			updateCaFile = makePath(str(
				configRoot.find("update").find("server").attrib["caFile"]))
			updateInterval = int(
				configRoot.find("update").find("general").attrib["interval"])
			updateEmailNotification = (str(
				configRoot.find("update").find("general").attrib[
				"emailNotification"]).upper() == "TRUE")

			# email notification works only if smtp is activated
			if (updateEmailNotification is True
				and smtpActivated is False):
				raise ValueError("Update check can not have email "
					+ "notification activated when smtp is not activated.")

		# Parse data collector settings.
		tempConf = configRoot.find("sensors")
		sensorDataCollector.apiKey = str(tempConf.attrib["apiKey"])
		sensorDataCollector.interval = int(tempConf.attrib["interval"])

		# parse all sensors
		for item in configRoot.find("sensors").iterfind("sensor"):

			sensorType = str(item.find("wunderground").attrib[
				"type"]).upper()

			if sensorType == "temperature".upper():

				sensor = WundergroundTempPollingSensor()

				# these options are needed by the server to
				# differentiate between the registered sensors
				sensor.id = int(item.find("general").attrib["id"])
				sensor.description = str(item.find("general").attrib[
					"description"])
				sensor.alertDelay = int(item.find("general").attrib[
					"alertDelay"])
				sensor.triggerAlert = (str(item.find("general").attrib[
					"triggerAlert"]).upper() == "TRUE")
				sensor.triggerAlertNormal = (str(item.find("general").attrib[
					"triggerAlertNormal"]).upper() == "TRUE")
				sensor.triggerState = 1

				sensor.alertLevels = list()
				for alertLevelXml in item.iterfind("alertLevel"):
					sensor.alertLevels.append(int(alertLevelXml.text))

				# Wunderground temperature specific settings
				sensor.country = str(item.find("wunderground").attrib[
					"country"])
				sensor.city = str(item.find("wunderground").attrib[
					"city"])

				# Register location in data collector.
				sensorDataCollector.addLocation(sensor.country,
					sensor.city)
				sensor.dataCollector = sensorDataCollector

			elif sensorType == "humidity".upper():

				sensor = WundergroundHumidityPollingSensor()

				# these options are needed by the server to
				# differentiate between the registered sensors
				sensor.id = int(item.find("general").attrib["id"])
				sensor.description = str(item.find("general").attrib[
					"description"])
				sensor.alertDelay = int(item.find("general").attrib[
					"alertDelay"])
				sensor.triggerAlert = (str(item.find("general").attrib[
					"triggerAlert"]).upper() == "TRUE")
				sensor.triggerAlertNormal = (str(item.find("general").attrib[
					"triggerAlertNormal"]).upper() == "TRUE")
				sensor.triggerState = 1

				sensor.alertLevels = list()
				for alertLevelXml in item.iterfind("alertLevel"):
					sensor.alertLevels.append(int(alertLevelXml.text))

				# Wunderground temperature specific settings
				sensor.country = str(item.find("wunderground").attrib[
					"country"])
				sensor.city = str(item.find("wunderground").attrib[
					"city"])

				# Register location in data collector.
				sensorDataCollector.addLocation(sensor.country,
					sensor.city)
				sensor.dataCollector = sensorDataCollector

			elif sensorType == "forecasttemp".upper():

				sensor = WundergroundForecastTempPollingSensor()

				# these options are needed by the server to
				# differentiate between the registered sensors
				sensor.id = int(item.find("general").attrib["id"])
				sensor.description = str(item.find("general").attrib[
					"description"])
				sensor.alertDelay = int(item.find("general").attrib[
					"alertDelay"])
				sensor.triggerAlert = (str(item.find("general").attrib[
					"triggerAlert"]).upper() == "TRUE")
				sensor.triggerAlertNormal = (str(item.find("general").attrib[
					"triggerAlertNormal"]).upper() == "TRUE")
				sensor.triggerState = 1

				sensor.alertLevels = list()
				for alertLevelXml in item.iterfind("alertLevel"):
					sensor.alertLevels.append(int(alertLevelXml.text))

				# Wunderground temperature specific settings
				sensor.country = str(item.find("wunderground").attrib[
					"country"])
				sensor.city = str(item.find("wunderground").attrib[
					"city"])
				sensor.kind = str(item.find("wunderground").attrib[
					"kind"]).upper()
				sensor.day = int(item.find("wunderground").attrib[
					"day"])

				# Sanity check of kind option.
				if (sensor.kind != "high".upper()
					and sensor.kind != "low".upper()):
					raise ValueError("Kind of sensor '%s' not valid."
						% sensor.kind)

				# Sanity check of day option.
				if sensor.day < 0 and sensor.day > 2:
					raise ValueError("Day of sensor '%d' not valid."
						% sensor.day)

				# Register location in data collector.
				sensorDataCollector.addLocation(sensor.country,
					sensor.city)
				sensor.dataCollector = sensorDataCollector

			elif sensorType == "forecastrain".upper():

				sensor = WundergroundForecastRainPollingSensor()

				# these options are needed by the server to
				# differentiate between the registered sensors
				sensor.id = int(item.find("general").attrib["id"])
				sensor.description = str(item.find("general").attrib[
					"description"])
				sensor.alertDelay = int(item.find("general").attrib[
					"alertDelay"])
				sensor.triggerAlert = (str(item.find("general").attrib[
					"triggerAlert"]).upper() == "TRUE")
				sensor.triggerAlertNormal = (str(item.find("general").attrib[
					"triggerAlertNormal"]).upper() == "TRUE")
				sensor.triggerState = 1

				sensor.alertLevels = list()
				for alertLevelXml in item.iterfind("alertLevel"):
					sensor.alertLevels.append(int(alertLevelXml.text))

				# Wunderground temperature specific settings
				sensor.country = str(item.find("wunderground").attrib[
					"country"])
				sensor.city = str(item.find("wunderground").attrib[
					"city"])
				sensor.day = int(item.find("wunderground").attrib[
					"day"])

				# Sanity check of day option.
				if sensor.day < 0 and sensor.day > 2:
					raise ValueError("Day of sensor '%d' not valid."
						% sensor.day)

				# Register location in data collector.
				sensorDataCollector.addLocation(sensor.country,
					sensor.city)
				sensor.dataCollector = sensorDataCollector

			else:
				raise ValueError("Type of sensor '%s' not valid."
					% sensorType)

			# check if description is empty
			if len(sensor.description) == 0:
				raise ValueError("Description of sensor %d is empty."
					% sensor.id)

			# check if the id of the sensor is unique
			for registeredSensor in globalData.sensors:
				if registeredSensor.id == sensor.id:
					raise ValueError("Id of sensor %d"
						% sensor.id + "is already taken.")

			if (not sensor.triggerAlert
				and sensor.triggerAlertNormal):
					raise ValueError("'triggerAlert' for sensor %d "
						% sensor.id + "has to be activated when "
						+ "'triggerAlertNormal' is activated.")

			globalData.sensors.append(sensor)

	except Exception as e:
		logging.exception("[%s]: Could not parse config." % fileName)
		sys.exit(1)

	random.seed()

	# check if smtp is activated => generate object to send eMail alerts
	if smtpActivated is True:
		globalData.smtpAlert = SMTPAlert(smtpServer, smtpPort,
			smtpFromAddr, smtpToAddr)
	else:
		globalData.smtpAlert = None

	# initialize logging
	logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s',
		datefmt='%m/%d/%Y %H:%M:%S', filename=logfile,
		level=loglevel)

	# check if sensors were found => if not exit
	if not globalData.sensors:
		logging.critical("[%s]: No sensors configured." % fileName)
		sys.exit(1)

	# Start data collector thread.
	# Set thread to daemon.
	# => Thread terminates when main thread terminates.
	sensorDataCollector.daemon = True
	sensorDataCollector.start()

	# Initialize sensors before starting worker threads.
	for sensor in globalData.sensors:
		if not sensor.initializeSensor():
			logging.critical("[%s]: Not able to initialize sensor."
				% fileName)
			sys.exit(1)

	# generate object for the communication to the server and connect to it
	globalData.serverComm = ServerCommunication(server, serverPort,
		serverCAFile, username, password, clientCertFile, clientKeyFile,
		globalData)
	connectionRetries = 1
	while True:
		# check if 5 unsuccessful attempts are made to connect
		# to the server and if smtp alert is activated
		# => send eMail alert
		if (globalData.smtpAlert is not None
			and (connectionRetries % 5) == 0):
			globalData.smtpAlert.sendCommunicationAlert(connectionRetries)

		if globalData.serverComm.initializeCommunication() is True:
			# if smtp alert is activated
			# => send email that communication problems are solved
			if not globalData.smtpAlert is None:
				globalData.smtpAlert.sendCommunicationAlertClear()

			connectionRetries = 1
			break
		connectionRetries += 1

		logging.critical("[%s]: Connecting to server failed. " % fileName
			+ "Try again in 5 seconds.")
		time.sleep(5)

	# when connected => generate watchdog object to monitor the
	# server connection
	watchdog = ConnectionWatchdog(globalData.serverComm,
		globalData.pingInterval, globalData.smtpAlert)
	# set thread to daemon
	# => thread terminates when main thread terminates
	watchdog.daemon = True
	watchdog.start()

	# only start update checker if it is activated
	if updateActivated is True:
		updateChecker = UpdateChecker(updateServer, updatePort, updateLocation,
			updateCaFile, updateInterval, updateEmailNotification, globalData)
		# set thread to daemon
		# => thread terminates when main thread terminates
		updateChecker.daemon = True
		updateChecker.start()

	# set up sensor executer and execute it
	# (note: we will not return from the executer unless the client
	# is terminated)
	sensorExecuter = SensorExecuter(globalData)
	sensorExecuter.execute()