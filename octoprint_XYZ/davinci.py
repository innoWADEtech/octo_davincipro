import logging
import os
import struct
import binascii
import Padding
from .gcode import GCodeFile
from io import BytesIO
from Crypto.Cipher.AES import AESCipher, MODE_ECB, MODE_CBC

log = logging.getLogger(__name__)

class ThreeWFile(object):
    @classmethod
    def from_file(cls, path):
        with open(path, 'rb') as f:
            return cls.from_string(f.read())

    @classmethod
    def from_string(cls, string):
        inst = cls()
        inst.decrypt(string)
        return inst

    def decrypt(self, string):
        enc_gcode = string[0x2000:]
        aes = AESCipher("@xyzprinting.com@xyzprinting.com", mode=MODE_ECB, IV=chr(0)*16)
        gcode = aes.decrypt(enc_gcode)
        self.gcode = GCodeFile.from_string(gcode)

    def encrypt_header(self):
        key = "@xyzprinting.com"
        iv = chr(0)*16
        aes = AESCipher(key, mode=MODE_CBC, IV=iv)
        text = self.gcode.header_text
        header = Padding.appendPadding(text)
        return aes.encrypt(header)

    def encrypt(self):
        key = "@xyzprinting.com@xyzprinting.com"
        iv = chr(0)*16
        aes = AESCipher(key, mode=MODE_ECB, IV=iv)
        fulltext = self.gcode.text
        padded = Padding.appendPadding(fulltext)
        enc_text = aes.encrypt(padded)

        magic = "3DPFNKG13WTW"
        magic2 = struct.pack("8B", 1, 2, 0, 0, 0, 0, 18, 76)
        blanks = chr(0)*4684
        tag = "TagEJ256"
        magic3 = struct.pack("4B", 0, 0, 0, 68)
        crc32 = binascii.crc32(enc_text)
        crcstr = struct.pack(">l", crc32)
        encrypted_header = self.encrypt_header()
        bio = BytesIO()
        bio.write(magic)
        bio.write(magic2)
        bio.write(blanks)
        bio.write(tag)
        bio.write(magic3)
        bio.write(crcstr)
        bio.write((chr(0)*(68 - len(crcstr))))
        log.debug("Length of encrypted header: {}".format(len(encrypted_header)))
        if len(encrypted_header) > (8192 - bio.tell()):
            log.error("Header is too big to fit file format!")
        bio.write(encrypted_header)
        left = 8192 - bio.tell()
        bio.write((chr(0)*left))
        bio.write(enc_text)
        return bio.getvalue()

    def __init__(self, gcode=None):
        self.gcode = gcode

    def write(self, path):
        with open(path, 'wb') as f:
            f.write(self.encrypt())


