# (c) Copyright 2009, Synapse Wireless, Inc.
"""
Reads an Intel HEX File

See: http://en.wikipedia.org/wiki/Intel_HEX
For file format information

Losely based on code from Alexander Belchenko:
http://www.bialix.com/intelhex/
"""
__docformat__ = "plaintext en"


import binascii
import array


class IntelHexReaderError(Exception):
    pass


class IntelHexData(object):
    def __init__(self, address, data, crc):
        self.address = address  #offset
        self.data = data #recdata
        self.crc = crc #not really needed long term
        self.length = binascii.unhexlify("%04x" % len(data))

    def get_int_address(self):
        return int(self.address, 16)

    int_address = property(get_int_address)


class IntelHexReader(object):
    def __init__(self):
        self._lines = [] #Raw text lines from input file
        self.data = [] #Holds IntelHexData objects containing continous data
        self.combined_data = []
        self.start_addr = {}

    def combine(self, length=512, full_size=4*0x8000-1, addr_adjust=4):
        #Initalize everything to FFs
        alldata = [chr(0xff)] * full_size

        # Build up a record that is full if possible and write it out.
        # The first one must be no more than 0x8000 * 2
        # The second is everything greater than 0x8000*2 or 0x10000
        currentPosition = 0
        for record in self.data:
            addr = int("%s" % binascii.hexlify(record.address), 16)
            len_int = int(binascii.hexlify(record.length), 16)
            alldata[addr:addr+len_int] = record.data

        #print "alldata length is %d" % len(alldata)

        for index in range(0, full_size, length):
            data = ''.join(alldata[index:index+length])
            bin = array.array('B', data)
            crc = (~sum(bin)+1) % 2**8
            addr = '%04X' % (index/addr_adjust)

            #Check to make sure that this data set is not all FFs
            if data != '\xff'*len(data):
                self.combined_data.append(IntelHexData(addr, data, crc))
            elif __debug__:
                print "dropping all FFs @", addr

        #Calc CRC of combined image and return it
        bin = array.array('B', ''.join(alldata))
        return sum(bin) % 2**8

    def get_data_generator(self):
        for obj in self.data:
            yield obj

    def get_combined_data_generator(self):
        for obj in self.combined_data:
            yield obj

    def read(self, file):
        self._lines = open(file, 'r').readlines()

    def writeeof(self, File):
        File.write(":00000001FF\r\n");

    def writebase(self, File, base):
        record = ':02000004%s' % (base)
        bin = array.array('B', binascii.unhexlify(record[1:]))
        crc = (~sum(bin)+1) % 2**8
        record += "%02X" % crc
        File.write((record))

    def write(self, file):
        Fout = open(file, 'w')
        alldata = [] # continous data
        for i in range((4*0x8000)-1):
            alldata.append(chr(255))
        self.writebase(Fout, "0000")

        # Build up a record that is full if possible and write it out.
        # The first one must be no more than 0x8000 * 2
        # The second is everything greater than 0x8000*2 or 0x10000
        currentPosition = 0
        for r in self.data:
            addr = ("%s" % binascii.hexlify(r.address))
            bin = array.array('B', binascii.unhexlify(addr[0:]))
            if len(bin) == 2:
                a = bin[0]*256 + bin[1]
            else:
                a = bin[0]*65536 + bin[1]*256 + bin[2]
            for p in range(len(r.data)):
                alldata[p+a] = r.data[p]

        #print "alldata length is %d" % len(alldata)

        counter = 15
        record = ':10000000'
        offset = 0
        for index in range(len(alldata)):
            record += "%02X" % ord(alldata[index])
            if not index == 0:
                if index == counter:
                    #print "length of record is %d index is: %X record is %s counter is %X" % (len(record), index, record, counter)
                    
                    bin = array.array('B', binascii.unhexlify(record[1:]))
                    #print "length of bin is %d" % len(bin)

                    testVal = (sum(bin[4:]))
                    #print "TestVal = %d" % testVal

                    #if not testVal == 2805:
                    if not testVal == 4080:
                        crc = (~sum(bin)+1) % 2**8
                        self.combined_data.append(IntelHexData(addr, record[9:], crc))
                        record += "%02X" % crc
                        Fout.write("\r\n")
                        Fout.write(record)
                    record = ':10%04X00' % ((index-offset)+1)
                    counter+=16
            if index == 0xFFFE:
                Fout.write("\r\n")
                self.writebase(Fout,"0001")
                #print "Changed Offset"
                offset = 0x10000

        Fout.write("\r\n")
        self.writebase(Fout,"0002")
        Fout.write("\r\n")

        self.writeeof(Fout)

    def verify(self, round, lines=None):
        if lines is None:
            lines = self._lines
        offset = '' #Used in change of base

        # loop through each line in the file
        for line in lines:
            # strip the \r\n from the line
            line = line.strip()
            # verify that the length is correct, and that we don't have a problem
            if line[0] != ':' or len(line) < 11:
                #According to file format there is always at least 11 bytes per line and starts with ":"
                raise IntelHexReaderError("Invalid line found in file")
            elif line[7:9] == "01":
                #Found what should be end of file
                break
            elif line[7:9] == "00":
                #Found data record
                # convert the data found between character 1 and the end minus 2 from hex
                # to unsigned char.  In the end there will be half the number
                try:
                    bin = array.array('B', binascii.unhexlify(line[1:-2]))
                except TypeError:
                    raise IntelHexReaderError("Found non-hex characters")

                # verify that the length of the record data matches that we were given
                # in the line
                if len(line[9:-2]) != bin[0]*2:
                    raise IntelHexReaderError("Record length values do not match")

                # save off the address by shifting the first char to the left 8 and adding
                # the second char of address.
                addr = bin[1]*256 + bin[2]
                #if addr > 0x8000:
                #    print "Got Big Address in file at %d" % (addr)

                # check the checksum of the data by adding up the entire sum of bin 
                # not sure what the plus 1 does and % with 256 to get the value left
                # to compare to the value at the end of the record
                crc = (~sum(bin)+1) % 2**8
                try:
                    if crc != int(line[-2:], 16):
                        raise IntelHexReaderError("Checksum values do not match")
                except ValueError:
                    raise IntelHexReaderError("Found non-hex characters in checksum")

                # now add this record to the data list of IntelHexData records by creating
                # a IntelHexData object and appending in one line.
                # What does the unhexlify("%04x" % addr) do?
                if round != 2:
                    self.data.append(IntelHexData(offset + binascii.unhexlify("%04x" % (addr)), binascii.unhexlify(line[9:-2]), crc))
                elif addr >= 0x8000:
                    addr += 0x8000
                    self.data.append(IntelHexData(binascii.unhexlify("%06x" % (addr)), binascii.unhexlify(line[9:-2]), crc))
            elif line[7:9] == "03":
                # Start Segment Address Record
                if line[1:3] != "04" or line[3:7] != "0000":
                    raise IntelHexReaderError("Invalid Start Segment Address Record")
                if self.start_addr:
                    raise IntelHexReaderError("Duplicate start address")
                rec = array.array('B', binascii.unhexlify(line[9:-2]))
                self.start_addr = {'CS': rec[0]*256 + rec[1],
                                   'IP': rec[2]*256 + rec[3],
                                  }
            elif line[7:9] == "04":
                # We have found a change base message
                if binascii.unhexlify(line[11:-2]) != '\x00':
                    offset = binascii.unhexlify(line[11:-2])
            elif line[7:9] == '05':
                pass
            else:
                #We don't currently support any other record types
                raise IntelHexReaderError("Unsupported record type")

def comIntelData(a,b) : return cmp(a.address, b.address)


if __name__ == '__main__':
    import getopt
    import os
    import sys

    usage = '''Hex2Bin python converting utility.
Usage:
    python intelhex.py [options] file.hex [out.bin]

Arguments:
    file.hex                name of hex file to processing.
    out.bin                 name of output file.
                            If omitted then output write to file.bin.

Options:
    -h, --help              this help message.
    -p, --pad=FF            pad byte for empty spaces (ascii hex value).
    -r, --range=START:END   specify address range for writing output
                            (ascii hex value).
                            Range can be in form 'START:' or ':END'.
    -l, --length=NNNN,
    -s, --size=NNNN         size of output (decimal value).
'''

    pad = 0xFF
    start = None
    end = None
    size = None

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hp:r:l:s:", 
				["help", "pad=", "range=",
				 "length=", "size="])

        for o, a in opts:
            if o in ("-h", "--help"):
                print usage
                sys.exit(0)
            elif o in ("-p", "--pad"):
                try:
                    pad = int(a, 16) & 0x0FF
                except:
                    raise getopt.GetoptError, 'Bad pad value'
            elif o in ("-r", "--range"):
                try:
                    l = a.split(":")
                    if l[0] != '':
                        start = int(l[0], 16)
                    if l[1] != '':
                        end = int(l[1], 16)
                except:
                    raise getopt.GetoptError, 'Bad range value(s)'
            elif o in ("-l", "--lenght", "-s", "--size"):
                try:
                    size = int(a, 10)
                except:
                    raise getopt.GetoptError, 'Bad size value'

        if start != None and end != None and size != None:
            raise getopt.GetoptError, 'Cannot specify START:END and SIZE simultaneously'

        if not args:
            raise getopt.GetoptError, 'Hex file is not specified'

        if len(args) > 2:
            raise getopt.GetoptError, 'Too many arguments'

    except getopt.GetoptError, msg:
        print msg
        print usage
        sys.exit(2)

    file1 = args[0]
    if len(args) == 1:
      import os.path
      name, ext = os.path.splitext(file1)
      fout = name + ".tmp"

    if not os.path.isfile(file1):
      print "File not found"
      sys.exit(1)

    #print "Procesing File 1"
    reader = IntelHexReader()
    reader.read(file1, 1)

    if ext == ".H00":
      file2 = name + ".H01"

    if not os.path.isfile(file2):
      print "Second Input not found\r\n"
    else:
      #print "Procesing File 2"
      reader.read(file2, 2)

    # Now we need to sort the data in the list.
    #reader.data.sort(comIntelData)

    #print "Combined Files" 
    #print "length is %d" % (len(reader.data))
    #for n in reader.data:
    #  print  binascii.hexlify(n.address), binascii.hexlify(n.data)

    reader.write(fout);
