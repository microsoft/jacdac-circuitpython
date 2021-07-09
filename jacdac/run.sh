#!/bin/sh

MPYC=../../circuitpython/mpy-cross/mpy-cross
set -e
set -x

# just validete with mpy-cross
for f in jacdac/*.py  ; do
  $MPYC $f
done
#rm -f jacdac/*.mpy

mkdir -p /Volumes/CIRCUITPY/jacdac
cp code.py /Volumes/CIRCUITPY/
cp jacdac/*.mpy /Volumes/CIRCUITPY/jacdac/
