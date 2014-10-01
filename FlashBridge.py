#!/usr/bin/env python
import os
import array
import binascii
import RF200Flasher
import optparse
import bz2
import sys
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

    parser = optparse.OptionParser(usage="""E10 Bridge Flashing Utility
 Usage:  FlashBridge.py -i [imagename] -p [port]""")

    parser.add_option("-e", "--erase", dest="erase", default=False,
                                action="store_true", 
                                help="Erase the current SnapPy script.")
    parser.add_option("-i", "--image", dest="image", default=None,
                                metavar="imageName", action="store",
                                help="The image file to flash.")
    parser.add_option("-n", "--defaultnv", dest="defaultnv",
                                action="store_true", default=False,
                                help="Reset the device's NV params.")

    parser.add_option("-p", "--port", dest="port", metavar="comport",
                        action="store", default='/dev/ttyS1',
                        help="Required:  The serial device to use.")

    (options, args) = parser.parse_args()
    
    if not (options.erase or options.image or options.defaultnv):
        print "Must specify either -e, -i, or -n" 
        sys.exit(1)
    
    return options


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
