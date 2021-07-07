#!/bin/sh

MPYC=../../circuitpython/mpy-cross/mpy-cross
set -e
set -x

# just validete with mpy-cross
$MPYC jacdac/*.py
rm -f jacdac/*.mpy

cp -r code.py jacdac /Volumes/CIRCUITPY/
