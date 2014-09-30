#!/usr/bin/env python
import subprocess
import tempfile
import os
import array
import binascii
import sys
import RF200Flasher
import argparse
import shutil
from FlashParams import FlashParams

#
# For Erasing Snappy Images
#

# MAGIC KEY related
MAGIC_KEY_CMD_DEFAULT_NV = 'N'
MAGIC_KEY_CMD_ERASE_SCRIPT = 'S'


def warnToKillSnapConnect():
    print "*** NOTE:\n"
    print "*** "
    print "*** This application will not work if you have not terminated "
    print "*** any SnapConnect applications that are communicating with "
    print "*** the SNAP device you wish to flash, erase, or NV default."
    print "*** "
    print "*** IF the program hangs, check to ensure a SnapConnect process "
    print "*** is not still running and try again."


def niceHex(number):
    numHex = hex(number)
    numHex = numHex[2:]  # chop off the leading '0x'
    if len(numHex) != 2:
        numHex = '0'+numHex  # tack on a leading '0' if not two digits
    numHex = numHex.upper()
    return numHex


def buildMagicHRec(cmdChar, addr='02F0'):
    magicKey = '524D44454D474B42'
    record = '09%s00%s%02X' % (addr, magicKey, ord(cmdChar))
    crc = (~sum(array.array('B', binascii.unhexlify(record)))+1) % 2**8

    # text = ':020000020000FC\n'  # Header
    text = ':%s%02X\n' % (record, crc)
    text += ':00000001FF'  # End of file record

    return text


def createFilesAndFilePaths(args, MAGIC_KEY_CMD):
    if(args.rf200):
        fd, atmega128rfa1_path = tempfile.mkstemp(prefix='ATmega128RFA1',
                                                  text=True)
        tempFile = os.fdopen(fd, 'w')
        tempFile.write(buildMagicHRec(MAGIC_KEY_CMD))
        tempFile.close()
        return atmega128rfa1_path


#
# ParseArgs - determine what module to flash
#
def parseArgs():
    parser = argparse.ArgumentParser(description="""E10 Bridge Flashing Utility
 Usage:  FlashBridge.py [bridgeType] -i [imagename] -p [port]""")

    radioTypeGroup = parser.add_mutually_exclusive_group(required=True)
    radioTypeGroup.add_argument("-rf200", action="store_true",
                                help="Specify the bridge node as an RF200")
    radioTypeGroup.add_argument("-ss200", action="store_true",
                                help="Specify the bridge node as an SS200")

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


#
# Functions to check if UserMain/SynapseMain are running
#
def scriptIsRunning(scriptName):
    psSub = subprocess.Popen(["ps"], stdout=subprocess.PIPE)
    grepSub = subprocess.Popen(["grep", "-e", "User\|SynapseMain"],
                               stdin=psSub.stdout, stdout=subprocess.PIPE)
    grep2Sub = subprocess.Popen(["grep", "-v", "grep"],
                                stdin=grepSub.stdout, stdout=subprocess.PIPE)
    (output, err) = subprocess.Popen(["cut", "-f1", "-d "],
                                     stdin=grep2Sub.stdout,
                                     stdout=subprocess.PIPE).communicate()

    if output == "":
        return False
    return True


def userMainIsRunning():
    return scriptIsRunning("UserMain")


def synapseMainIsRunning():
    return scriptIsRunning("SynapseMain")


#
# Image file validation and extraction
#
def fileIsType(imageFileName, typeName):
    (output, err) = subprocess.Popen(["file", imageFileName],
                                     stdout=subprocess.PIPE).communicate()
    words = output.split(':')
    if len(words) < 2:
        print "An error occurred attempting to inspect the \
file type of ", imageFileName
        return False

    output = words[1]
    if output.find(typeName) == -1:
        return False
    return True


def imageFileIsASCII(imageFileName):
    expectedType = "ASCII text"
    return fileIsType(imageFileName, expectedType)


def imageFileIsSFI(imageFileName):
    expectedType = "bzip2 compressed data"
    return fileIsType(imageFileName, expectedType)


def extractAndGetNewPath(sfiFileName):
    tmpDir = tempfile.mkdtemp()
    shutil.copy(sfiFileName, tmpDir)

    cwd = os.getcwd()
    os.chdir(tmpDir)
    bzipCommand = "bzip2 -dck " + sfiFileName + " > snap.image"
    os.system(bzipCommand)
    os.chdir(cwd)
    return tmpDir + "/snap.image"


#
# Sanity Check - Make sure UserMain/SynapseMain aren't running before we
#                start, and verify that the image files are the right type.
#
def sanityCheck(args, imageFilePath):
    if userMainIsRunning() is True:
        print "UserMain.py is running.  \
Please stop UserMain.py before continuing."
        sys.exit(0)
    elif synapseMainIsRunning() is True:
        print "SynapseMain.py is running.  \
Please stop SynapseMain.py before continuing."
        sys.exit(0)

    if args.rf200 is True:
        if imageFileIsASCII(imageFilePath) is False:
            print args.image, " does not appear to be a valid image file!"
            sys.exit(0)


if __name__ == '__main__':
    args = parseArgs()

    if args.erase:
        imageFilePath = createFilesAndFilePaths(args,
                                                MAGIC_KEY_CMD_ERASE_SCRIPT)
        print "Erase"
    elif args.defaultnv:
        imageFilePath = createFilesAndFilePaths(args,
                                                MAGIC_KEY_CMD_DEFAULT_NV)
        print "Default NV"
    else:
        if imageFileIsSFI(args.image):
            imageFilePath = extractAndGetNewPath(args.image)
        else:
            imageFilePath = args.image
        sanityCheck(args, imageFilePath)

    warnToKillSnapConnect()
    flashParams = FlashParams(imageFilePath, args.port)

    if args.rf200 is True:
        RF200Flasher.flash(flashParams)
    elif args.ss200 is True:
        import RF200Flasher
        RF200Flasher.flash(flashParams)
