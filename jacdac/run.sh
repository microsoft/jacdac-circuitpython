#!/bin/sh

MPYC=../../circuitpython/mpy-cross/mpy-cross
set -e
set -x

$MPYC jacdac.py
cp code.py jacdac.py /Volumes/CIRCUITPY/
