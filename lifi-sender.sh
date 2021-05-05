#!/bin/bash

# Take a file, chop it up, convert it to a stream of QR code and display it
# in sequence Can be received by web app using lifi-receiver.js

CHUNKSIZE=300
FPS=3
REPEAT=1

usage() {
    echo "Usage: $0 [-c <chunksize>] [-f <fps>] [-r <repeat>] file" 1>&2
    exit 1
}

while getopts 'c:f:r:' o
do
    case $o in
        c)  CHUNKSIZE=$OPTARG;;
        f)  FPS=$OPTARG;;
        r)  REPEAT=$OPTARG;;
        *)  usage
    esac
done

shift $((OPTIND-1))

if [ ! -r "$1" ]; then
    echo "File not provided or unreadable" 1>&2
    exit 1
fi

file=$1
size=`wc -c < $file`
delay=`echo 1/$FPS | bc -l`
chunks=$((size / CHUNKSIZE + 1))

r=0
while [ $r -lt $REPEAT ]; do
    i=0
    while [ $i -lt $chunks ]; do
        clear
        dd if=$file bs=$CHUNKSIZE skip=$i count=1 2>/dev/null | (echo -n "L1FB,1,$file,$chunks,$i,"; base64) | qrencode -t ANSI256
        sleep $delay
        i=$((i + 1))
    done
    r=$((r + 1))
done
