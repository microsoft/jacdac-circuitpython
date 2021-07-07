#!/bin/sh

MPYC=../../circuitpython/mpy-cross/mpy-cross
set -e
set -x

# just validete with mpy-cross
for f in jacdac/*.py ; do
  $MPYC $f
done
rm -f jacdac/*.mpy

cp -r code.py jacdac /Volumes/CIRCUITPY/
