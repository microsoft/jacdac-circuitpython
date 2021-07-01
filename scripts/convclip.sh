#!/bin/sh

pbpaste | node topy.js > tmp.py
pbcopy < tmp.py
rm -f tmp.py
