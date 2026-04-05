#! /usr/bin/env python3

# Upload Pioneer dash cam photos from SD card to Mapillary.

# 1. Moves front video and nmea files from SD card to "<yyyy-mm-dd>_<area>" directory under work directory
#    Where <yyyy-mm-dd> is the starting date from the NMEA file and <area> is the reverse geocoded name of the start position
#    1a. Ignore files without GPS lock or if entire video is stationary
#    1b. Renames .NMEA files to have lowercase extension
#    1c. Converts .nmea file to .gpx files with `gpsbabel`
# 2. Foreach  "<yyyy-mm-dd>_<area>" directory created:
#    2a. Use mapillary_tools to process videos with .nmea file
#    2b. Use mapillary_tools to upload videos

# TODO: Process rear camera photos as well?  (FILEE*.MP4)
# TODO: Remove rear camera and skipped files from SD Card?
#
# NOTE: Process with NMEA no longer works, get 0 meta data and file does not upload
#       Converting .nmea file to GPX with https://mygeodata.cloud/ or `gpsbabel` 
#       and uploading MP4 file with .gpx file via Linux desktop uploader works
#       This script has been modified to convert .nmea file to .gpx via `gpsbabel`
#       (install with apt) and process with .gpx files.

import argparse
import calendar
import datetime
import os
from pathlib import Path
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
parser.add_argument("--dontProcess", "-dp", help="Don't process or upload videos to Mapillary",
                    action="store_true")
parser.add_argument("--dontUpload", "-du", help="Don't upload videos to Mapillary",
                    action="store_true")
args = parser.parse_args()

configFile = Path.home() / ".config" / "dashcam.json"

config = json.load(open(configFile))
sdcardDir = config['sdcard_dir']
workDir = config['work_dir']

if not os.path.isdir(sdcardDir):
    print(f"SDCard directory '{sdcardDir}' Does not exist")
    exit(1)

if not os.path.isdir(workDir):
    print(f"Destination '{workDir}' Does not exist")
    exit(1)

workDir=workDir+"/Downloaded-"+datetime.datetime.now().strftime('%Y-%m-%d')

# FIXME: Create a new directory if workDir exists
if not os.path.isdir(workDir):
    os.mkdir(workDir)
    print(f"{workDir} created.")
else:
    print(f"{workDir} exists.")

# -----------------------------------------------------------------
def errhandler(err):
    """
    Handles errors output by iterator.
    """

    print(f"\nERROR Parsing .nmea file: {err}\n")

def parse_nmea(path, name):
    """
    Parse .nmea file for start date/time, start lat, start lon, end lat and end lon
    """

    startTime = None
    startLat = None
    startLon = None
    endTime = None
    endLat = None
    endLon = None
    date = None
    stationary = True

    with open(path, "rb") as stream:
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
        print(f"-- Stationary video, {name}")

    if date and not stationary:
        gmtStart = time.strptime(f"{str(date)} {str(startTime)[:8]}", "%Y-%m-%d %H:%M:%S")
        localStart = time.localtime(calendar.timegm(gmtStart))

        # Return time.struct_time, (lat, lon), (lat, lon)
        return localStart, (startLat, startLon), (endLat, endLon)
    else:
        return None,  (None, None), (None, None)

# -----------------------------------------------------------------
def convert_nmea_to_gpx(inputNmea, outputGpx):
    # Construct the command as a list of arguments
    command = [
        "gpsbabel",
        "-i", "nmea", "-f", inputNmea,
        "-o", "gpx", "-F", outputGpx
    ]
    
    try:
        # Run the command
        subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"++ Successfully converted '{inputNmea}' to '{outputGpx}'")
    except subprocess.CalledProcessError as e:
        print(f"-- Error during conversion of '{inputNmea}' to '{outputGpx}': {e.stderr}")


# -----------------------------------------------------------------
class Geocode:
  def __init__(self):
    Geocode.geolocator = Nominatim(user_agent="Process_And_Upload_Dashcam")
    Geocode.last = None;

  def reverse(self, coords):

      if coords is None:
          print("No lat/lon, not moving")
          return None
      else:
          if Geocode.last and ((datetime.datetime.now()-Geocode.last).total_seconds() < 2):
            time.sleep(2)

          # FIXME: Retry if reverse geocoding fails 
          try:
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
            elif 'county' in location.raw['address']:
                locName=location.raw['address']['county']
            elif 'state' in location.raw['address']:
                locName=location.raw['address']['state']
            elif 'name' in location.raw['address']:
                locName=location.raw['address']['name']
            else:
              print(f"WARNING: No location from - {location.raw}")
              locName="UNKNOWN"

            locName=locName.replace(" ","_")
          except Exception as inst:
            print(f"WARNING: Unable to reverse geocode")
            locName="UNKNOWN"

          return locName

# -----------------------------------------------------------------
# Transfer .MP4 and .NMEA files from SDCARD

dirs=[]

geo=Geocode()

for entry in os.scandir(sdcardDir):
    if entry.name.endswith(".NMEA"):
        name, ext=os.path.splitext(entry.name)
        startDateTime, start, end=parse_nmea(entry.path, name)

        # Ignore files that don't have a start time (GPS lock not obtained)
        if not startDateTime:
            print(f"-- No time/date parsed from .nmea file or stationary video, skip '{name}'")
            continue


        # Ignore video within delta of ignore co-ords from config file
        ignoreVideo = False
        for ignore in config['ignore']:
            if distance.distance((ignore['lat'],ignore['lon']), start).km < ignore['delta']:
                print(f"-- Start close to {ignore['name']}, skip {name}")
                ignoreVideo = True

            elif distance.distance((ignore['lat'],ignore['lon']), end).km < ignore['delta']:
                print(f"-- End close to {ignore['name']}, skip {name}")
                ignoreVideo = True

        # Transfer .MP4 and .NMEA files from SD card to "<yyyy-mm-dd>" directory under work directory
        if not ignoreVideo:

            area=geo.reverse(start)

            destDir=workDir+"/"+time.strftime('%Y-%m-%d',startDateTime)+"_"+area
            if destDir not in dirs:
                dirs.append(destDir)

            if not os.path.isdir(destDir):
                os.mkdir(destDir)

            destNmea=os.path.join(destDir, entry.name.replace(".NMEA",".nmea"))
            destGpx=os.path.join(destDir, entry.name.replace(".NMEA",".gpx"))

            srcMp4=entry.path.replace(".NMEA",".MP4")
            if args.copy:
                print(f"++ Copy {name} files to {destDir}")
                shutil.copy(entry.path, destNmea)
                shutil.copy(srcMp4, destDir)
            else:
                print(f"++ Move {name} files to {destDir}")
                shutil.move(entry.path, destNmea)
                shutil.move(srcMp4, destDir)

            # Convert .nmea file in destDir to .gpx
            convert_nmea_to_gpx(destNmea, destGpx)


# -----------------------------------------------------------------
# Use mapillary_tools to process videos, directory at a time

for dir in dirs:
  if args.dontProcess:
    print(f"Not processing or uploading '{dir}' for Mapillary")
  else:
    print(f"Process '{dir}', using .gpx file")
    subprocess.call(["mapillary_tools","process","--video_geotag_source","gpx",dir])

# -----------------------------------------------------------------
# Use mapillary_tools to upload processed videos, directory at a time

for dir in dirs:
    if args.dontProcess or args.dontUpload:
      print(f"Not uploading '{dir}' to Mapillary")
    else:
      print(f"Upload '{dir}'")
      subprocess.call(["mapillary_tools","upload",dir])


