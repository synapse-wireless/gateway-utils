#!/usr/bin/env python
# Copyright 2009-2014, Synapse Wireless Inc., All rights Reserved.
#
# Neither the name of Synapse nor the names of contributors may be used to
# endorse or promote products derived from this software without specific
# prior written permission.
#
# This software is provided "AS IS," without a warranty of any kind. ALL
# EXPRESS OR IMPLIED CONDITIONS, REPRESENTATIONS AND WARRANTIES, INCLUDING ANY
# IMPLIED WARRANTY OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE OR
# NON-INFRINGEMENT, ARE HEREBY EXCLUDED. SYNAPSE AND ITS LICENSORS SHALL NOT BE
# LIABLE FOR ANY DAMAGES SUFFERED BY LICENSEE AS A RESULT OF USING, MODIFYING
# OR DISTRIBUTING THIS SOFTWARE OR ITS DERIVATIVES. IN NO EVENT WILL SYNAPSE OR
# ITS LICENSORS BE LIABLE FOR ANY LOST REVENUE, PROFIT OR DATA, OR FOR DIRECT,
# INDIRECT, SPECIAL, CONSEQUENTIAL, INCIDENTAL OR PUNITIVE DAMAGES, HOWEVER
# CAUSED AND REGARDLESS OF THE THEORY OF LIABILITY, ARISING OUT OF THE USE OF
# OR INABILITY TO USE THIS SOFTWARE, EVEN IF SYNAPSE HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGES.
"""Upgrades SNAP core, erase script files, and factory defaults
NVParameters for attached bridge nodes"""


import os
import array
import binascii
import RF200Flasher
import optparse
import bz2
import sys
from cStringIO import StringIO


# MAGIC KEY related
MAGIC_KEY_CMD_DEFAULT_NV = 'N'
MAGIC_KEY_CMD_ERASE_SCRIPT = 'S'


def build_magic_hrec(cmd, addr='02F0'):
    """Build a magical Intel Hex file to erase
    scripts or default NV parameters"""
    magic = '524D44454D474B42'
    record = '09%s00%s%02X' % (addr, magic, ord(cmd))
    crc = (~sum(array.array('B', binascii.unhexlify(record)))+1) % 2**8

    text = ':%s%02X\n' % (record, crc)
    text += ':00000001FF'  # End of file record
    return text


def parse_args():
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

    (options, _) = parser.parse_args()

    if not (options.erase or options.image or options.defaultnv):
        print "Must specify either -e, -i, or -n"
        sys.exit(1)

    try:
        options.port = int(options.port )
    except ValueError:
        pass
    
    return options


def main():
    ARGS = parse_args()

    if ARGS.erase:
        FP = StringIO(build_magic_hrec(MAGIC_KEY_CMD_ERASE_SCRIPT))
        print "Erase"
    elif ARGS.defaultnv:
        FP = StringIO(build_magic_hrec(MAGIC_KEY_CMD_DEFAULT_NV))
        print "Default NV"
    else:
        # Assume that the file is an SFI file
        FP = bz2.BZ2File(ARGS.image, 'r')
        try:
            # Try to go to the end of the file
            FP.seek(-1, os.SEEK_END)
            # And move back to the beginning
            FP.seek(0, os.SEEK_SET)
        except IOError:
            # If we got an IOError, assume we were not an SFI file
            # and open the file normally
            FP = open(ARGS.image, 'rb')

    RF200Flasher.flash(FP, ARGS.port)


if __name__ == '__main__':
    main()
