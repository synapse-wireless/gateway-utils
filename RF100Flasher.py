# (c) Copyright 2007-2012 Synapse Wireless, Inc.
"""Programs an S19 file into flash"""
__docformat__ = "plaintext en"


import logging, binascii, datetime, time
log = logging.getLogger(__name__)

import pys19, FlashParams
from serialwrapper import PyserialDriver
import sys
import os

DEFAULT_IDENT = "GB/GT60"
MC1321X_IDENT = "MC1321x"
RFENGINE_IDENT = "RFEngine"

#class FlashParams:
#    def __init__(self, imageFilename, comPort):
#        self.imageFilename = imageFilename
#        self.comPort = comPort 

class Hcs08Flasher(object):
    IDENT_COMMAND = "\x49"
    ACK_COMMAND = "\xfc"
    ERASE_COMMAND = "\x45"
    WRITE_COMMAND = "\x57"
    READ_COMMAND = "\x52"
    QUIT_COMMAND = "\x51"

    def __init__(self, filename, scheduler=None, finishedCallback=None, serialDrv=None, verifyWrite=True, writeRetries=3, timeout=2, 
                 type=PyserialDriver.PyserialWrapper.TYPE_PYSERIAL, port=0, pathToUsbLibrary='.', file_ident=None):
        self.s19 = pys19.S19(byteBoundary=64)
        self.s19.read(filename)
        if serialDrv is None:
            self.serialDrv = PyserialDriver.PyserialWrapper(dllPath=pathToUsbLibrary)
        else:
            self.serialDrv = serialDrv
        assert isinstance(self.serialDrv, PyserialDriver.PyserialWrapper)
        self.serialDrv.BAUDRATE = 9600
        self.serialDrv.registerRxCallback(self.onRead)
        self.type = type
        self.port = port
        self.serialDrv.setOutputType(self.type, self.port)
        #self.serialDrv.serial.setDTR(0)
        #self.serialDrv.serial._reconfigurePort()
        self.fcCntr = 0
        self._waitingForIdent = False
        self._waitingForInitialFc = True
        self._sendingS19 = False
        self._sentErase = False
        self._sentWrite = False
        self._doneSending = False
        self._sentRead = False
        self.identData = ''
        self.readSupported = False
        self.finishedSuccessfully = False
        self.vectorRelocateOffset = 0x200 #We could calc this based off ident info
        self.eraseLength = 512 #We could calc this based off ident info
        self.origVectorLoc = 0xFFC0 #We could calc this based off ident info
        self._lastEraseLoc = 0
        self._nextS19 = 0
        self._rec = None
        self._curdata = ''
        self.verifyWrite = verifyWrite
        self.writeRetries = writeRetries
        self._lastData = datetime.datetime.now()
        self.timeout = datetime.timedelta(seconds=timeout)
        self._retryCntr = 0
        self.finishedCallback = finishedCallback
        self.scheduler = scheduler
        self.scheduler.scheduleEvent(self.checkTimeout, delay=timeout)
        self.scheduler.scheduleEvent(self.poll)
        self.progressCallbacks = []
        self.errorCallbacks = []
        self.turboMode = True
        self._inClose = False
        self.max_progress = len(self.s19.splitdata)-1
        self.file_ident = file_ident

    def checkTimeout(self):
        if not self._waitingForInitialFc and not self.finishedSuccessfully and datetime.datetime.now()-self._lastData > self.timeout:
            self._tellError(Exception("Did not receive response within timeout"))
            return False
        return True

    def checkV4Boot(self):
        if self._waitingForInitialFc and self.fcCntr == 1:
            #Send calibration pulse
            self.serialDrv.serial.parity = PyserialDriver.serial.PARITY_EVEN
            self.serialDrv.write("\x00")
            self.turboMode = False
    def close(self):
        self._inClose = True

    def onRead(self, data):
        self._lastData = datetime.datetime.now()
        if self._sentRead:
            self._curdata += data
            if len(self._curdata) == self._rec.len:
                if self._rec.data == self._curdata:
                    #log.debug("%04x Verified" % self._rec.startMemLoc)
                    self._nextS19 += 1
                    self._retryCntr = 0
                else:
                    log.error("%04X Did NOT Verify" % self._rec.startMemLoc)
                    if self._retryCntr > self.writeRetries:
                        self._tellError(Exception("Unable to write at memory location"))
                        self._waitingForInitialFc = True #Don't "timeout"
                    self._retryCntr += 1
                self._sentRead = False
                self._curdata = ''
                self.sendNext()

#        if (data == '\xfc') or (self._waitingForInitialFc and '\xfc' in data): # <- works, possibly too lenient
        if (data == '\xfc') or (self._waitingForInitialFc and (data[-1] == '\xfc')): # works too
            self._lastData = datetime.datetime.now()
            #log.debug("Got FC")
            if self._waitingForInitialFc:
                if self.fcCntr == 0:
                    self.serialDrv.write(self.ACK_COMMAND)
                    self.scheduler.schedule(0.5, self.checkV4Boot)
                else:
                    if not self.turboMode:
                        #Set parity back
                        self.serialDrv.serial.parity = PyserialDriver.serial.PARITY_NONE
                    self.serialDrv.write(self.IDENT_COMMAND)
                    self._waitingForInitialFc = False
                    self._waitingForIdent = True
            if self._sendingS19:
                if self._sentErase:
                    self._sentErase = False
                elif self._sentWrite:
                    self._sentWrite = False
                    if self.verifyWrite and self.readSupported:
                        self._sentRead = True
                        #log.debug("Sent READ")
                        self.serialDrv.write("%s%s%s" % (self.READ_COMMAND, binascii.unhexlify("%04x" % self._rec.startMemLoc), binascii.unhexlify("%02x" % self._rec.len)))
                    else:
                        self._nextS19 += 1
                if not self._doneSending and not self._sentRead:
                    self.sendNext()
            self.fcCntr += 1
        elif self._waitingForIdent:
            self.identData += data
            if len(self.identData) > 20 and self.identData[-1:] == '\x00':
                if int(binascii.hexlify(self.identData[0]), 16) & 0x0f != 2:
                    self._tellError(Exception("Unsupported bootloader version"))
                if __debug__:
                    log.debug("Found: %s" % self.identData[20:-1])
                if (self.file_ident is not None and 
                    self.identData[20:-1] != DEFAULT_IDENT and
                    self.file_ident != self.identData[20:-1]):
                    self._tellError(Exception("The selected file is not supported on this platform"))
                    self.serialDrv.close()
                    self.timeout = datetime.timedelta.max
                    return
                self.readSupported = int(binascii.hexlify(self.identData[0]), 16) >> 7 == 1
                if __debug__:
                    self.printIdentInfo()
                self._waitingForIdent = False
                self._sendingS19 = True
                if self.turboMode:
                    self.serialDrv.write("\x54")
                    if sys.platform.startswith("darwin"): # #4360 Make sure the 0x54 actually makes it out
                        self.serialDrv.serial.flush() # Someday may make this unconditional, but original symptoms were Mac-specific
                    #self.serialDrv.serial.setBaudrate(115200) #Baudrate is changeable on the fly
                    self.serialDrv.close()
                    self.serialDrv.BAUDRATE = 115200
                    self.serialDrv.setOutputType(self.type, self.port)
                else:
                    #Enable turbo mode posibility for next upgrade
                    self.turboMode = True
                self.sendNext()

    def poll(self):
        #print "%f" % time.clock()
        self.serialDrv.readPoll()
        self.serialDrv.writePoll()
        if self._inClose:
            try:
                self.serialDrv.close()
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                log.debug("An error occurred while closing the serial driver:")
            return False
        return True

    def printIdentInfo(self):
        log.debug("Version Number and Capabilities: %s" % binascii.hexlify(self.identData[0]))
        log.debug("Read Command Supported: %i" % (int(binascii.hexlify(self.identData[0]), 16) >> 7))
        log.debug("Bootloader Version: %i" % (int(binascii.hexlify(self.identData[0]), 16) & 0x0f))
        log.debug("System device Identification register content: %s" % binascii.hexlify(self.identData[1:3]))
        log.debug("Number of reprogrammable memory areas: %s" % binascii.hexlify(self.identData[3]))
        log.debug("Start address of reprogrammable memory area #1: %s" % binascii.hexlify(self.identData[4:6]))
        log.debug("End address of reprogrammable memory area #1: %s" % binascii.hexlify(self.identData[6:8]))
        log.debug("Start address of reprogrammable memory area #2: %s" % binascii.hexlify(self.identData[8:10]))
        log.debug("End address of reprogrammable memory area #2: %s" % binascii.hexlify(self.identData[10:12]))
        log.debug("Address of relocated interrupt vector table: %s" % binascii.hexlify(self.identData[12:14]))
        log.debug("Start address of MCU interrupt vector table: %s" % binascii.hexlify(self.identData[14:16]))
        log.debug("Length of MCU erase block: %s" % binascii.hexlify(self.identData[16:18]))
        log.debug("Length of MCU write block: %s" % binascii.hexlify(self.identData[18:20]))
        log.debug("Identification string: %s" % self.identData[20:-1])

    def registerErrorCallback(self, callback):
        if callable(callback):
            self.errorCallbacks.append(callback)

    def registerProgressCallback(self, callback):
        if callable(callback):
            self.progressCallbacks.append(callback)

    def sendNext(self):
        for callback in self.progressCallbacks:
            try:
                callback(self._nextS19)
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                log.exception("An error occurred while notifying a callback about progress")

        try:
            self._rec = self.s19.splitdata[self._nextS19]
            assert isinstance(self._rec, pys19.SData)
            if self._rec.startMemLoc >= self.origVectorLoc:
                self._rec.startMemLoc -= self.vectorRelocateOffset
        except IndexError:
            self._doneSending = True
            self.serialDrv.write(self.QUIT_COMMAND)
            if __debug__:
                log.debug("DONE")
            self.serialDrv.close()
            self.finishedSuccessfully = True
            if callable(self.finishedCallback):
                self.finishedCallback()
            return

        if self._lastEraseLoc == 0 or self._rec.startMemLoc+self._rec.len > self._lastEraseLoc+self.eraseLength:
            eraseLoc = (self._rec.startMemLoc/self.eraseLength) * self.eraseLength
            if eraseLoc >= int(binascii.hexlify(self.identData[6:8]), 16) and eraseLoc <= int(binascii.hexlify(self.identData[8:10]), 16):
                eraseLoc = int(binascii.hexlify(self.identData[8:10]), 16)
            #We might want to do this:
            #elif eraseLoc < int(binascii.hexlify(self.identData[4:6]), 16):
                #eraseLoc = int(binascii.hexlify(self.identData[4:6]), 16)
            if eraseLoc == self._lastEraseLoc:
                eraseLoc += self.eraseLength
            self._lastEraseLoc = eraseLoc
            #The first chunk of FLASH on the 9S08 is funny
            if eraseLoc < 0x1080:
                eraseLoc = 0x1080
            if __debug__:
                log.debug("Erasing @ %04x" % ( eraseLoc ))
            self.serialDrv.write("%s%s" % (self.ERASE_COMMAND, binascii.unhexlify("%04x" % ( eraseLoc ))))
            self._sentErase = True
        else:
            if __debug__:
                log.debug("Writing @ %04x with %02x bytes" % (self._rec.startMemLoc, self._rec.len))
            self.serialDrv.write("%s%s%s%s" % (self.WRITE_COMMAND, binascii.unhexlify("%04x" % self._rec.startMemLoc), binascii.unhexlify("%02x" % self._rec.len), self._rec.data))
            self._sentWrite = True

    def _tellError(self, exception):
        for callback in self.errorCallbacks:
            try:
                callback(exception)
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                log.exception("An error occurred while notifying a callback of an error:")

def flash(flashParams):
    """This code is needed to run as a stand alone program"""
    from apy import EventScheduler
    
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s:%(msecs)03d %(levelname)-8s %(name)-8s %(message)s', datefmt='%H:%M:%S')
    
    evScheduler = EventScheduler.EventScheduler()
    flasher = Hcs08Flasher(flashParams.imageFilename, evScheduler, port=flashParams.comport)
    evScheduler.scheduleEvent(flasher.poll)
    
    # os.system("echo 0 > /sys/class/gpio/gpio75/value")
    # time.sleep(0.5)
    # os.system("echo 1 > /sys/class/gpio/gpio75/value")
    
    os.system("sh resetBridge.sh")
    
    # startTime = time.time()
    firstTime = True
    while flasher.finishedSuccessfully == False:
        # print "still flashing"
        evScheduler.poll()
        # if flasher.Upgrading == True and firstTime:
        #     firstTime = False
        #     print "Firsttime = False"
        time.sleep(0.005)

if __name__ == '__main__':
    flashParams = FlashParams('RF100_SNAP.S19', port='/dev/ttyS1')
    flash(flashParams)
      

