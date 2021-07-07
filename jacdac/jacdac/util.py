import struct

_hex = "0123456789abcdef"


def hex_num(n: int, len=8):
    r = "0x"
    for i in range(len):
        r += _hex[(n >> ((len - 1 - i) * 4)) & 0xf]
    return r


def buf2hex(buf: bytes):
    r = ""
    # is this quadartic?
    for b in buf:
        r += _hex[b >> 4] + _hex[b & 0xf]
    return r


def hex2buf(s: str):
    r = bytearray(len(s) >> 1)
    for idx in range(0, len(s), 2):
        r[idx >> 1] = (_hex.index(s[idx].lower()) <<
                       4) | _hex.index(s[idx+1].lower())
    return r


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
