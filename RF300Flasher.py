# (c) Copyright 2009, Synapse Wireless, Inc.
"""Programs a hex file into the flash of an Si1000"""
__docformat__ = "plaintext en"


import logging, binascii, datetime, time, array, struct
log = logging.getLogger(__name__)
if __debug__:
    import pprint

import pyintelhex, FlashParams
from serialwrapper import PyserialDriver


HELLO_INCOMING = '\xf9'
HELLO_OUTGOING = '\xf6'
BLOCK_COMMAND = 'b'
SIGNATURE_COMMAND = 's'
INFO_COMMAND = 'I'
ADDRESS_COMMAND = 'A'
EXIT_COMMAND = 'E'

ADDRESS_RESPONSE = '\r'
EXIT_RESPONSE = '\r'

SI1000_SIGNATURE = '\xD0'
SI1001_SIGNATURE = '\xD1'
SI1002_SIGNATURE = '\xD2'
SI1003_SIGNATURE = '\xD3'
SI1004_SIGNATURE = '\xD4'
SUPPORTED_SIGNATURES = [SI1000_SIGNATURE, SI1002_SIGNATURE, SI1004_SIGNATURE]

SUPPORTED_VERSIONS = (1,)

SI1000_IDENT = "Si1000"


class FlasherError(Exception):
    pass


class Si1000Flasher(object):
    STATE_IDLE = 0
    STATE_INCOMING_WAIT = 1
    STATE_BLOCK_CMD_RESPONSE = 2
    STATE_SIGNATURE_RESPONSE = 3
    STATE_INFO_RESPONSE = 4
    STATE_ADDRESS_RESPONSE = 5
    STATE_DATA_RESPONSE = 6
    STATE_EXIT_RESPONSE = 7
    STATE_TIMEOUT = 8

    START_ADDRESS = 0

    def __init__(self,
                 filename,
                 scheduler=None,
                 finishedCallback=None,
                 serialDrv=None,
                 verifyWrite=True,
                 writeRetries=3,
                 timeout=2,
                 type=PyserialDriver.PyserialWrapper.TYPE_PYSERIAL,
                 port=0,
                 pathToUsbLibrary='.',
                 prompt_func=None,
                 info_func=None):
        if serialDrv is None:
            self.serialDrv = PyserialDriver.PyserialWrapper(dllPath=pathToUsbLibrary)
        else:
            self.serialDrv = serialDrv
        assert isinstance(self.serialDrv, PyserialDriver.PyserialWrapper)
        self.serialDrv.BAUDRATE = 115200
        self.serialDrv.registerRxCallback(self.onRead)
        self.type = type
        self.port = port
        self.serialDrv.setOutputType(self.type, self.port)
        self.verifyWrite = verifyWrite
        self.writeRetries = writeRetries
        self._lastData = datetime.datetime.now()+datetime.timedelta(hours=24)
        self.timeout = datetime.timedelta(seconds=timeout)
        self._retryCntr = 0
        self.finishedCallback = finishedCallback
        self.scheduler = scheduler
        #assert isinstance(scheduler, EventScheduler.EventScheduler)
        self.scheduler.scheduleEvent(self.poll)
        self.progressCallbacks = []
        self.errorCallbacks = []
        self._inClose = False
        self.progress_cntr = 0
        self.prompt_func = prompt_func
        self.info_func = info_func

        self.state = self.STATE_INCOMING_WAIT
        self.state_handlers = {self.STATE_IDLE: self.handle_idle,
                               self.STATE_INCOMING_WAIT: self.handle_incoming,
                               self.STATE_BLOCK_CMD_RESPONSE: self.handle_block_mode,
                               self.STATE_SIGNATURE_RESPONSE: self.handle_signature,
                               self.STATE_INFO_RESPONSE: self.handle_info,
                               self.STATE_ADDRESS_RESPONSE: self.handle_address,
                               self.STATE_DATA_RESPONSE: self.handle_data,
                               self.STATE_EXIT_RESPONSE: self.handle_exit}
        self._data_buff = ''

        self.image = pyintelhex.IntelHexReader()
        self.image.read(filename)
        self.image.verify(round=1)
        #self._combined_crc = image.combine(length=FLASH_PAGE_SIZE, full_size=FLASH_FULL_SIZE)
        #self._combined_data = image.get_combined_data_generator()
        self._combined_data = None
        self._curr_combined_data = ''
        self._curr_combined_address = 0

        self.max_progress = 1000

        self.block_len = 0
        self.version_found = 0
        self.num_blocks = 0
        self.last_data = ''
        self.finishedSuccessfully = False

    def _check_timeout(self):
        if self.state != self.STATE_IDLE and datetime.datetime.now()-self._lastData > self.timeout:
            self.state = self.STATE_TIMEOUT
            self.serialDrv.close()
            log.error("A data timeout has occurred")
            self._tellError(FlasherError("Data timeout"))
            return False
        return True

    def close(self):
        self.serialDrv.close()
        self.state = self.STATE_IDLE

    def handle_address(self):
        if self._data_buff == ADDRESS_RESPONSE:
            self.send_next_data()
            self._data_buff = ''
        else:
            self._tellError(FlasherError("Unit was unable to change block address"))

    def handle_block_mode(self):
        try:
            (confirmation, block_len) = struct.unpack(">cH", self._data_buff)
        except struct.error:
            log.info("Did not receive expected block mode message")
            return

        if confirmation == 'Y':
            self.block_len = block_len
            self.send_signature_command()
        else:
            self._tellError(FlasherError("Could not enter block mode"))
        self._data_buff = ''

    def handle_data(self):
        if len(self._data_buff) >= 2:
            received_checksum = struct.unpack(">H", self._data_buff)[0]
            data_checksum = sum(map(ord, self._curr_combined_data)) & 0xFFFF
            if received_checksum == data_checksum:
                self._curr_combined_data = ''
                self._retryCntr = 0
                self.send_next_data()
            elif self._retryCntr > self.writeRetries:
                log.error("Maximum number of retries reached")
                self._tellError(FlasherError("Maximum number of retries reached"))
            else:
                log.debug("Retrying data, received checksum %i, should be %i" % (received_checksum, data_checksum))
                self._retryCntr += 1
                #self.send_data(self._curr_combined_data)
                self.send_set_address(self._curr_combined_address)
            self._data_buff = ''

    def handle_exit(self):
        log.info("Flasher Finished!")
        if callable(self.finishedCallback):
            self.finishedCallback()
        self.finishedSuccessfully = True
        self.close()

    def handle_idle(self):
        if __debug__:
            log.debug("HANDLE IDLE: %i=%s" % (self.state, self._data_buff))
        self._data_buff = ''

    def handle_incoming(self):
        if self._data_buff == HELLO_INCOMING:
            self.serialDrv.write(HELLO_OUTGOING)
            self.send_block_command()
            self.scheduler.scheduleEvent(self._check_timeout, delay=self.timeout.seconds)
            self.update_progess()
        else:
            log.info("Did not receive expected hello message")
        self._data_buff = ''

    def handle_info(self):
        try:
            (ver, num_blocks) = struct.unpack(">BH", self._data_buff)
        except struct.error:
            self._tellError(FlasherError("Did not receive supported info message"))
            return

        if ver in SUPPORTED_VERSIONS:
            self.num_blocks = num_blocks
            self._combined_crc = self.image.combine(length=self.block_len,
                                                    full_size=self.block_len*self.num_blocks,
                                                    addr_adjust=1)
            self._combined_data = self.image.get_combined_data_generator()
            self.max_progress = len(self.image.combined_data)+3
            ihrec = self._combined_data.next()
            self._lastData = datetime.datetime.now() #Update time just in case the combine took a while

            self.send_set_address(ihrec.address)
            self._curr_combined_data = ihrec.data
            self._curr_combined_address = ihrec.int_address
        else:
            self._tellError(FlasherError("Device is running an unsupported version"))
        self._data_buff = ''

    def handle_signature(self):
        if self._data_buff in SUPPORTED_SIGNATURES:
            self.send_info_command()
        else:
            self._tellError(FlasherError("Unsupported signature received"))
        self._data_buff = ''

    def onRead(self, data):
        if __debug__:
            log.debug("onRead: %s" % pprint.pformat(data))
        self._lastData = datetime.datetime.now()
        self._data_buff += data
        self.state_handlers.get(self.state, self.handle_idle)()
        pass

    def poll(self):
        print "%f" % time.clock()
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

    def registerErrorCallback(self, callback):
        if callable(callback):
            self.errorCallbacks.append(callback)

    def registerProgressCallback(self, callback):
        if callable(callback):
            self.progressCallbacks.append(callback)

    def send_block_command(self):
        log.debug("send_block_command")
        self.serialDrv.write(BLOCK_COMMAND)
        self.state = self.STATE_BLOCK_CMD_RESPONSE
        self.update_progess()

    def send_data(self, data):
        #log.debug("send_data @%s" % (self._curr_combined_address))
        print "send_data @%s" % (self._curr_combined_address)
        if isinstance(data, str):
            data = tuple(map(ord, data))
        assert isinstance(data, tuple)
        self.serialDrv.write(struct.pack(">c%dB" % (self.block_len), "B", *data))
        self.state = self.STATE_DATA_RESPONSE
        self.last_data = data
        self.update_progess()

    def send_exit(self):
        log.debug("send_exit")
        self.serialDrv.write(EXIT_COMMAND)
        self.state = self.STATE_EXIT_RESPONSE

    def send_info_command(self):
        log.debug("send_info_command")
        self.serialDrv.write(INFO_COMMAND)
        self.state = self.STATE_INFO_RESPONSE
        self.update_progess()

    def send_next_data(self):
        if not self._curr_combined_data:
            try:
                ihrec = self._combined_data.next()
            except StopIteration:
                log.debug("Finished sending data")
                self.send_exit()
                return

            self._curr_combined_data = ihrec.data
            self._curr_combined_address = ihrec.int_address

            if ihrec.int_address != self._curr_combined_address+self.block_len:
                self.send_set_address(ihrec.address)
                return

        self.send_data(self._curr_combined_data)

    def send_set_address(self, addr):
        if isinstance(addr, str):
            addr = int(addr, 16)
        addr = addr
        log.debug("send_set_address(%04x)" % (addr))
        self.serialDrv.write(struct.pack(">cH", ADDRESS_COMMAND, addr))
        self.state = self.STATE_ADDRESS_RESPONSE

    def send_signature_command(self):
        log.debug("send_signature_command")
        self.serialDrv.write(SIGNATURE_COMMAND)
        self.state = self.STATE_SIGNATURE_RESPONSE
        self.update_progess()

    def _tellError(self, exception, close=True):
        log.error(str(exception))
        for callback in self.errorCallbacks:
            try:
                callback(exception)
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                log.exception("An error occurred while notifying a callback of an error:")
        if close:
            self.close()

    def update_progess(self):
        self.progress_cntr += 1
        for callback in self.progressCallbacks:
            try:
                callback(self.progress_cntr)
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                log.exception("An error occurred while notifying a callback about progress")

def flash(flashParams):
    import sys, os
    sys.path.append('..')
    from apy import EventScheduler

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s:%(msecs)03d %(levelname)-8s %(name)-8s %(message)s', datefmt='%H:%M:%S')

    evScheduler = EventScheduler.EventScheduler()

    flasher = Si1000Flasher(flashParams.imageFilename, evScheduler, port=flashParams.comport)
    evScheduler.scheduleEvent(flasher.poll)

    #os.system("echo 0 > /sys/class/gpio/gpio75/value")
    #time.sleep(0.5)
    #os.system("echo 1 > /sys/class/gpio/gpio75/value")

    os.system("sh resetBridge.sh")
    while flasher.finishedSuccessfully is False:
        #print "still flashing."
        evScheduler.poll()
        time.sleep(0.005)



if __name__ == '__main__':
    #import cProfile
    import sys, os
    sys.path.append('..')
    from apy import EventScheduler

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s:%(msecs)03d %(levelname)-8s %(name)-8s %(message)s', datefmt='%H:%M:%S')

    evScheduler = EventScheduler.EventScheduler()
    flasher = Si1000Flasher(r"Si1000.hex", evScheduler, port='/dev/ttyS1')
    evScheduler.scheduleEvent(flasher.poll)

    os.system("sh resetBridge.sh")
    while flasher.finishedSuccessfully is False:
        evScheduler.poll()
        time.sleep(0.005)
#    #cProfile.run('evScheduler.poll()', "C:\\synapse\\Portal\\trunk\\FlasherProfile.tmp")
