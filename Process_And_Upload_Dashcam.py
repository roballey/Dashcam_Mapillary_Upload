#! /usr/bin/env python3

# Upload Pioneer dash cam photos from SD card to Mapillary.

# 1. Moves front video and nmea files from SD card to "<yyyy-mm-dd>" directory under work directory
#    1a. Ignore files without GPS lock
#    1b. Renames .NMEA files to have lowercase extension
# 2. Foreach  "<yyyy-mm-dd>" directory created:
#    2a. Use mapillary_tools to process with .nmea filke
#    2b. Use mapillary_tools to upload

# TODO: Process rear camera photos as well?  (FILEE*.MP4)
# TODO: Remove rear camera and skipped files from SD Card?
# TODO: Put nmea and vide files in directory named after geocode of start

import argparse
import calendar
import datetime
import os
import shutil
import subprocess
import sys
import time

import json
from geopy import distance
from geopy.geocoders import Nominatim
from pynmeagps.nmeareader import NMEAReader

parser = argparse.ArgumentParser()
parser.add_argument("--copy", "-c", help="Copy files from SD card instead of moving",
                    action="store_true")
parser.add_argument("--dont_process", "-dp", help="Don't process or upload videos to Mapillary",
                    action="store_true")
parser.add_argument("--dont_upload", "-du", help="Don't upload videos to Mapillary",
                    action="store_true")
args = parser.parse_args()

config = json.load(open("dashcam.json"))
sdcardDir = config['sdcard_dir']
workDir = config['work_dir']

if not os.path.isdir(sdcardDir):
    print(f"SDCard directory '{sdcardDir}' Does not exist")
    exit(1)

if not os.path.isdir(workDir):
    print(f"Destination '{workDir}' Does not exist")
    exit(1)

# -----------------------------------------------------------------
def errhandler(err):
    """
    Handles errors output by iterator.
    """

    print(f"\nERROR Parsing NMEA file: {err}\n")

def parse_nmea(filename):
    """
    Parse nmea file for start date/time, start lat, start lon, end lat and end lon
    """

    startTime = None
    startLat = None
    startLon = None
    endTime = None
    endLat = None
    endLon = None
    date = None
    stationary = True

    with open(filename, "rb") as stream:
        nmr = NMEAReader(stream, nmeaonly=False, quitonerror=False, errorhandler=errhandler)
        for raw, parsed_data in nmr:
            if parsed_data:
                if parsed_data.msgID == "GGA":
                    if not startTime:
                        startTime=parsed_data.time
                        startLat=parsed_data.lat
                        startLon=parsed_data.lon
                    endTime=parsed_data.time
                    endLat=parsed_data.lat
                    endLon=parsed_data.lon
                    if (endLat != startLat) or (endLon != startLon):
                        stationary=False
                if parsed_data.msgID == "RMC":
                    if not date:
                        date=parsed_data.date

    if stationary:
        print(f"-- Stationary video, {filename}")

    if date and not stationary:
        gmtStart = time.strptime(f"{str(date)} {str(startTime)}", "%Y-%m-%d %H:%M:%S")
        localStart = time.localtime(calendar.timegm(gmtStart))

        # Return time.struct_time, (lat, lon), (lat, lon)
        return localStart, (startLat, startLon), (endLat, endLon)
    else:
        return None,  (None, None), (None, None)

class Geocode:
  def __init__(self):
    Geocode.geolocator = Nominatim(user_agent="Process_And_Upload_Dashcam")
    Geocode.last = None;

  def reverse(self, coords):

      if coords is None:
          print("No lat/lon, not moving")
          return None
      else:
          if Geocode.last and ((datetime.datetime.now()-Geocode.last).total_seconds() < 3):
            time.sleep(3)

          location = Geocode.geolocator.reverse(coords)
          Geocode.last=datetime.datetime.now()

          locName=""
          if 'hamlet' in location.raw['address']:
              locName=location.raw['address']['hamlet']
          elif 'village' in location.raw['address']:
              locName=location.raw['address']['village']
          elif 'suburb' in location.raw['address']:
              locName=location.raw['address']['suburb']
          elif 'town' in location.raw['address']:
              locName=location.raw['address']['town']
          elif 'city' in location.raw['address']:
              locName=location.raw['address']['city']
          else:
              print(f"{fullName} No location from - {location.raw}")

          locName=locName.replace(" ","_")
          return locName

# -----------------------------------------------------------------

dirs=[]

geo=Geocode()

for entry in os.scandir(sdcardDir):
    if entry.name.endswith(".NMEA"):
        name, ext=os.path.splitext(entry.name)
        startDateTime, start, end=parse_nmea(entry.path)

        # Ignore files that don't have a start time (GPS lock not obtained)
        if not startDateTime:
            print(f"-- No time/date parsed from NMEA or stationary video, skip {name}")
            continue

        area=geo.reverse(start)

        # Ignore video within delta of ignore co-ords from config file
        ignore_video = False
        for ignore in config['ignore']:
            if distance.distance((ignore['lat'],ignore['lon']), start).km < ignore['delta']:
                print(f"-- Start close to {ignore['name']}, skip {area} {name}")
                ignore_video = True

            elif distance.distance((ignore['lat'],ignore['lon']), end).km < ignore['delta']:
                print(f"-- End close to {ignore['name']}, skip {area} {name}")
                ignore_video = True

        # Move files from SD card to "<yyyy-mm-dd>" directory under work directory
        if not ignore_video:

            dir=workDir+time.strftime('%Y-%m-%d',startDateTime)+"_"+area
            if dir not in dirs:
                dirs.append(dir)

            if not os.path.isdir(dir):
                os.mkdir(dir)

            dest=os.path.join(dir, entry.name.replace(".NMEA",".nmea"))

            src=entry.path.replace(".NMEA",".MP4")
            if args.copy:
                print(f"++ Copy {name} files to {dir}")
                shutil.copy(entry.path, dest)
                shutil.copy(src, dir)
            else:
                print(f"++ Move {name} files to {dir}")
                shutil.move(entry.path, dest)
                shutil.move(src, dir)


for dir in dirs:
  if args.dont_process:
    print(f"Not processing {dir} for Mapillary")
  else:
    print(f"Process {dir}")
    subprocess.call(["mapillary_tools","process","--video_geotag_source","nmea",dir])

for dir in dirs:
    if args.dont_process or args.dont_upload:
      print(f"Not uploading {dir} to Mapillary")
    else:
      print(f"Upload {dir}")
      subprocess.call(["mapillary_tools","upload",dir])
