#!/usr/bin/env python
import os
import array
import binascii
import RF200Flasher
import argparse
import bz2
from cStringIO import StringIO

#
# For Erasing Snappy Images
#

# MAGIC KEY related
MAGIC_KEY_CMD_DEFAULT_NV = 'N'
MAGIC_KEY_CMD_ERASE_SCRIPT = 'S'


def buildMagicHRec(cmdChar, addr='02F0'):
    """Build a magical Intel Hex file to erase
    scripts or default NV parameters"""
    magicKey = '524D44454D474B42'
    record = '09%s00%s%02X' % (addr, magicKey, ord(cmdChar))
    crc = (~sum(array.array('B', binascii.unhexlify(record)))+1) % 2**8

    text = ':%s%02X\n' % (record, crc)
    text += ':00000001FF'  # End of file record
    return text


def parseArgs():
    """Parse the arguments passed in on the command line
    to determine which function to perform"""

    parser = argparse.ArgumentParser(description="""E10 Bridge Flashing Utility
 Usage:  FlashBridge.py -i [imagename] -p [port]""")

    flashTypeGroup = parser.add_mutually_exclusive_group(required=True)
    flashTypeGroup.add_argument("-e", "--erase", dest="erase",
                                action="store_true", required=False,
                                help="Erase the current SnapPy script.")
    flashTypeGroup.add_argument("-i", "--image", dest="image",
                                metavar="imageName", action="store",
                                required=False,
                                help="The image file to flash.")
    flashTypeGroup.add_argument("-nv", "--defaultnv", dest="defaultnv",
                                action="store_true", required=False,
                                help="Reset the device's NV params.")

    parser.add_argument("-p", "--port", dest="port", metavar="comport",
                        action="store", required=True,
                        help="Required:  The serial device to use.")

    return parser.parse_args()


if __name__ == '__main__':
    args = parseArgs()

    if args.erase:
        fp = StringIO(buildMagicHRec(MAGIC_KEY_CMD_ERASE_SCRIPT))
        print "Erase"
    elif args.defaultnv:
        fp = StringIO(buildMagicHRec(MAGIC_KEY_CMD_DEFAULT_NV))
        print "Default NV"
    else:
        # Assume that the file is an SFI file
        fp = bz2.BZ2File(args.image, 'r')
        try:
            # Try to go to the end of the file
            fp.seek(-1, os.SEEK_END)
            # And move back to the beginning
            fp.seek(0, os.SEEK_SET)
        except IOError:
            # If we got an IOError, assume we were not an SFI file
            # and open the file normally
            fp = open(args.image, 'rb')

    RF200Flasher.flash(fp, args.port)
