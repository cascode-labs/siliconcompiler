#!/bin/sh

OPT=$1
sc examples/gcd/gcd.v \
   -pdk_rev "1.0" \
   -target "freepdk45" \
   -asic_diesize "0 0 100.13 100.8" \
   -asic_coresize "10.07 11.2 90.25 91" \
   -loglevel "INFO" \
   -design gcd \
   -quiet $OPT
