# (c) Copyright 2007, Synapse
"""Reads an S19 File"""
__docformat__ = "plaintext en"


import binascii


MAX_ADDRESS = 0x1000000


def getNextBlock(addr, blockSize):
    return MAX_ADDRESS - (blockSize * (1 + ( (MAX_ADDRESS-(addr+blockSize)-1) / blockSize) ) )
    #return ((MAX_ADDRESS - (blockSize) *(1 + ((MAX_ADDRESS-((addr)+(blockSize))-1) / (blockSize)))))


class SData(object):
    def __init__(self, startMemLoc, data):
        self.startMemLoc = startMemLoc
        self.data = data

    def getLen(self):
        return len(self.data)

    def getChecksum(self):
        #hexData = "%02x%04x%s" % (len(self.data)+3, self.startMemLoc, binascii.hexlify(self.data))
        #return (~((sum([int(binascii.hexlify(self.data),16) for i in range(0,len(self.data),2)]) + len(hexData) + 3 + (self.startMemLoc & 0xFF) + ((self.startMemLoc>>8) & 0xFF)) & 0xFF)) & 0xFF
        return (~((sum([int(binascii.hexlify(self.data)[i:i+2],16) for i in range(0,len(self.data)*2,2)]) + len(self.data) + 3 + (self.startMemLoc & 0xFF) + ((self.startMemLoc>>8) & 0xFF)) & 0xFF)) & 0xFF

    len = property(getLen)
    checksum = property(getChecksum)


class S19(object):
    def __init__(self, byteBoundary=64):
        """
        maxBytes -- Maximum number of bytes to hold
        """
        self._lines = [] #Raw text lines from input file
        self.data = [] #Holds SData object containing continousdata
        self.splitdata = [] #Holds SData objects split up at byteBoundary
        self.byteBoundary = byteBoundary
        self._nextMemLoc = 0
        self._curRecord = None

    def read(self, file):
        self._lines = open(file, 'r').readlines()
        self.verify()

    def verify(self, lines=None):
        if lines is None:
            lines = self._lines

        for line in lines:
            line = line.strip()
            if len(line) < 6 and line[0] == 'S':
                #According to file format there is always at least 6 bytes per line and starts with "S"
                raise Exception("Invalid S19 File")
            if line[1] == '0':
                #descriptive information identifying the following block of S-records.
                pass
            elif line[1] == '1':
                _len = int(line[2:4], 16)
                if _len*2 != len(line[4:]):
                    raise Exception("Length of record not equal to what is reported")
                hexData = line[8:-2]
                memLoc = int(line[4:8], 16)
                if int(line[-2:], 16) != (~((sum([int(hexData[i:i+2],16) for i in range(0,len(hexData),2)]) + _len + (memLoc & 0xFF) + ((memLoc>>8) & 0xFF)) & 0xFF)) & 0xFF:
                    raise Exception("Checksum mismath")

                if self._curRecord and self._curRecord.startMemLoc+self._curRecord.len == memLoc:
                    self._curRecord.data += binascii.unhexlify(hexData)
                else:
                    if self._curRecord:
                        self.data.append(self._curRecord)
                    self._curRecord = SData(memLoc, binascii.unhexlify(hexData))
                pass
            elif line[1] == '9':
                #A termination record for a block of S1 records.
                pass
            else:
                raise Exception("Unhandled Record Type: %s" % line[1])
        self.data.append(self._curRecord) #Don't forget the last record

        for sdata in self.data:
            assert isinstance(sdata, SData)
            memLoc = sdata.startMemLoc
            while sdata.data:
                nextBondary = getNextBlock(memLoc, self.byteBoundary)
                getLen = nextBondary - memLoc
                #print "memLoc: %04X nextBondary: %04X getLen: %04X" % (memLoc, nextBondary, getLen)
                self.splitdata.append(SData(memLoc, sdata.data[:getLen]))
                sdata.data = sdata.data[getLen:]
                memLoc = nextBondary


if __name__ == '__main__':
    s19 = S19()
    s19.read("\\synapse\\Portal\\trunk\\firmware\\SnapV2.0.25.S19")
    print "file looks good"
