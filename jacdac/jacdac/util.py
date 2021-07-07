import struct
import ubinascii

def hex_num(n: int, len=8):
    hex = "0123456789abcdef"
    r = "0x"
    for i in range(len):
        r += hex[(n >> ((len - 1 - i) * 4)) & 0xf]
    return r


def buf2hex(buf: bytes):
    return str(ubinascii.hexlify(buf), "utf-8")


def u16(buf: bytes, off: int):
    return buf[off] | (buf[off+1] << 8)


def set_u16(buf: bytearray, off: int, val: int):
    buf[off] = val & 0xff
    buf[off + 1] = val >> 8


def u32(buf: bytes, off: int):
    return buf[off] | (buf[off+1] << 8) | (buf[off+2] << 16) | (buf[off+3] << 24)


# TODO would we want the "u32 u16" kind of format strings?
def unpack(buf: bytes, fmt: str = None):
    if fmt is None or buf is None:
        return buf
    return struct.unpack("<" + fmt, buf)


def pack(fmt: str, *args):
    if len(args) == 1 and isinstance(args[1], tuple):
        args = args[1]
    return struct.pack("<" + fmt, *args)


