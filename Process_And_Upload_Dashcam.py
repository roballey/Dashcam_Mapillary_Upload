#! /usr/bin/python3

# Upload Pioneer dash cam photos from SD card to Mapillary.

# 1. Moves front video and nmea files from SD card to "<yyyy-mm-dd>" directory under work directory
#    1a. Ignore files without GPS lock
#    1b. Renames .NMEA files to have lowercase extension
# 2. Foreach  "<yyyy-mm-dd>" directory created:
#    2a. Use mapillary_tools to process with .nmea filke
#    2b. Use mapillary_tools to upload

# TODO: Process rear camera photos as well?  (FILEE*.MP4)
# TODO: Remove rear camera and skipped files from SD Crad?

import calendar
import datetime
import os
import shutil
import subprocess
import sys
import time

import json
from geopy import distance
from pynmeagps.nmeareader import NMEAReader

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
                if parsed_data.msgID == "RMC":
                    if not date:
                        date=parsed_data.date

    if date and startLat and startLon:
        gmtStart = time.strptime(f"{str(date)} {str(startTime)}", "%Y-%m-%d %H:%M:%S")
        localStart = time.localtime(calendar.timegm(gmtStart))

        # Return time.struct_time, (lat, lon), (lat, lon)
        return localStart, (startLat, startLon), (endLat, endLon)
    else:
        return None,  (None, None), (None, None)

# -----------------------------------------------------------------

dirs=[]

for entry in os.scandir(sdcardDir):
    if entry.name.endswith(".NMEA"):
        startDateTime, start, end=parse_nmea(entry.path)

        # Ignore files that don't have a start time (GPS lock not obtained)
        if not startDateTime:
            print(f"-- No time/date parsed from NMEA, skip {entry.name}")
            continue

        # Ignore video within delta of ignore co-ords from config file
        ignore_video = False
        for ignore in config['ignore']:
            if distance.distance((ignore['lat'],ignore['lon']), start).km < ignore['delta']:
                print(f"-- Start close to {ignore['name']}, skip {entry.name}")
                ignore_video = True

            elif distance.distance((ignore['lat'],ignore['lon']), end).km < ignore['delta']:
                print(f"-- End close to {ignore['name']}, skip {entry.name}")
                ignore_video = True

        # Move files from SD card to "<yyyy-mm-dd>" directory under work directory
        if not ignore_video:
            dir=workDir+time.strftime('%Y-%m-%d',startDateTime)
            dirs.append(dir)

            if not os.path.isdir(dir):
                os.mkdir(dir)

            dest=os.path.join(dir, entry.name.replace(".NMEA",".nmea"))

            print(f"++ Move from {entry.path} to {dest}")
            shutil.move(entry.path, dest)

            src=entry.path.replace(".NMEA",".MP4")
            print(f"++ Move from {src} to {dir}")
            shutil.move(src, dir)
        print("\n")

for dir in dirs:
    print(f"Process {dir}")
    subprocess.call(["mapillary_tools","process","--video_geotag_source","nmea",dir])

for dir in dirs:
    print(f"Upload {dir}")
    subprocess.call(["mapillary_tools","upload",dir])
