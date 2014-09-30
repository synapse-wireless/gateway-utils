#!/bin/sh

GPIODIR='/sys/class/gpio'
RESETDIR='/sys/class/gpio/gpio75'

if [ ! -d "$RESETDIR" ] ; then
	echo 75 > $GPIODIR/export
	echo "out" > $RESETDIR/direction
	echo 1 > $RESETDIR/value
fi

echo 0 > $RESETDIR/value
sleep 1
echo 1 > $RESETDIR/value
