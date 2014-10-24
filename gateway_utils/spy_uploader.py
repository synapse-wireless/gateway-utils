#!/usr/bin/env python
# Copyright 2012-2014, Synapse Wireless Inc., All rights Reserved.
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


import sys
import os
import time
import datetime
import binascii

from snapconnect import snap

from snaplib import ScriptsManager, SnappyUploader, RpcCodec


BRIDGE_TIMEOUT = 2.5  # seconds


class SpyUploader:
    def __init__(self, filename, serial_type=snap.SERIAL_TYPE_RS232, serial_port=0):
        self.filename = filename
        self.running = True
        self.remote_addr = None
        try:
            _port = int(serial_port)
        except ValueError:
            _port = serial_port

        # Create a SNAP Connect object to do communications (comm) for us
        self.comm = snap.Snap(funcs={'tellVmStat': lambda *args: self.comm.spy_upload_mgr.onTellVmStat(self.comm.rpc_source_addr(), *args),
                                     'su_recvd_reboot': lambda *args: self.comm.spy_upload_mgr.on_recvd_reboot(self.comm.rpc_source_addr())})
        self.comm.save_nv_param(snap.NV_FEATURE_BITS_ID, 0x0100)  # RPC CRC
        RpcCodec.validateCrc = False
        self.comm.register_callback('next_hop_addr', lambda remote_addr, intf: self.start_upload(remote_addr))

        self.comm.open_serial(serial_type, _port)
        self.comm.scheduler.schedule(BRIDGE_TIMEOUT, self._bridge_timeout)

    def _bridge_timeout(self):
        if self.remote_addr is None:
            print "Unable to determine SNAP bridge node address"
            sys.exit(1)

    def start_upload(self, remote_addr):
        """Called internally for every upload attempt. You should be calling beginUpload()"""
        self.remote_addr = remote_addr
        try:
            f = open(self.filename, 'rb')
            try:
                spy = ScriptsManager.getSnappyStringFromExport(f.read())
            finally:
                f.close()
        except IOError:
            print "Unable to read SPY file"
            sys.exit(1)

        upload = self.comm.spy_upload_mgr.startUpload(remote_addr, spy)
        upload.registerFinishedCallback(self._upload_finished)
        self.running = True

    def _upload_finished(self, snappy_upload_obj, result):
        if result == SnappyUploader.SNAPPY_PROGRESS_COMPLETE:
            print "Successfully uploaded the SPY file"
            sys.exit(0)
        else:
            print "SPY file was NOT uploaded successfully"
            sys.exit(result)
        self.running = False


def main():
    from optparse import OptionParser

    parser = OptionParser("usage: %prog [options]")
    parser.add_option("-t", "--serial_type", default=1, dest="serial_type", help="Specifies the serial port type to open (Default RS-232")
    parser.add_option("-p", "--serial_port", default=0, dest="serial_port", help="Specifies the serial port name or number to open (Default 0)")
    parser.add_option("-f", "--filename", dest="filename", help="The SPY file to upload")
    (options, args) = parser.parse_args()

    if options.filename is None:
        print "A SPY filename is required"
        sys.exit(1)
    elif not os.path.isfile(options.filename):
        print "The SPY file specified does not exist"
        sys.exit(1)

    uploader = SpyUploader(options.filename, options.serial_type, options.serial_port)
    while uploader.running:
        uploader.comm.loop()


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    main()
