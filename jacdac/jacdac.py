from busio import JACDAC
from micropython import const
import time
import struct
import microcontroller
import supervisor
import ubinascii
import tasko

JD_SERIAL_HEADER_SIZE = const(16)
JD_SERIAL_MAX_PAYLOAD_SIZE = const(236)
JD_SERVICE_INDEX_MASK = const(0x3f)
JD_SERVICE_INDEX_INV_MASK = const(0xc0)
JD_SERVICE_INDEX_CRC_ACK = const(0x3f)
JD_SERVICE_INDEX_PIPE = const(0x3e)
JD_SERVICE_INDEX_CTRL = const(0x00)

JD_FRAME_FLAG_COMMAND = const(0x01)
JD_FRAME_FLAG_ACK_REQUESTED = const(0x02)
JD_FRAME_FLAG_IDENTIFIER_IS_SERVICE_CLASS = const(0x04)

# Registers 0x001-0x07f - r/w common to all services
# Registers 0x080-0x0ff - r/w defined per-service
# Registers 0x100-0x17f - r/o common to all services
# Registers 0x180-0x1ff - r/o defined per-service
# Registers 0x200-0xeff - custom, defined per-service
# Registers 0xf00-0xfff - reserved for implementation, should not be on the wire

CMD_GET_REG = const(0x1000)
CMD_SET_REG = const(0x2000)
CMD_TYPE_MASK = const(0xf000)
CMD_REG_MASK = const(0x0fff)
CMD_EVENT_MASK = const(0x8000)
CMD_EVENT_CODE_MASK = const(0xff)
CMD_EVENT_COUNTER_MASK = const(0x7f)
CMD_EVENT_COUNTER_POS = const(8)

EV_CHANGE = const("change")
EV_DEVICE_CONNECT = const("deviceConnect")
EV_DEVICE_CHANGE = const("deviceChange")
EV_DEVICE_ANNOUNCE = const("deviceAnnounce")
EV_SELF_ANNOUNCE = const("selfAnnounce")
EV_PACKET_PROCESS = const("packetProcess")
EV_REPORT_RECEIVE = const("reportReceive")
EV_REPORT_UPDATE = const("reportUpdate")
EV_RESTART = const("restart")
EV_PACKET_RECEIVE = const("packetReceive")
EV_EVENT = const("packetEvent")
EV_STATUS_EVENT = const("statusEvent")
EV_IDENTIFY = const("identify")

_ACK_RETRIES = const(4)
_ACK_DELAY = const(40)


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


# TODO implement this in C for half-decent precision
def now():
    return int(time.monotonic() * 1000)


# TODO would we want the "u32 u16" kind of format strings?
def unpack(buf: bytes, fmt: str = None):
    if fmt is None or buf is None:
        return buf
    return struct.unpack(fmt, buf)


def pack(fmt: str, *args):
    return struct.pack(fmt, *args)


class JDPacket:
    def __init__(self, *, cmd: int = None, size: int = 0, frombytes: bytes = None) -> None:
        self.timestamp = now()
        if frombytes is None:
            self._header = bytearray(JD_SERIAL_HEADER_SIZE)
            self._data = bytearray(size)
        else:
            self._header = bytearray(frombytes[0:JD_SERIAL_HEADER_SIZE])
            self._data = bytearray(frombytes[JD_SERIAL_HEADER_SIZE:])
        if cmd is not None:
            self.service_command = cmd

    @property
    def service_command(self):
        return u16(self._header, 14)

    @service_command.setter
    def service_command(self, cmd: int):
        set_u16(self._header, 14, cmd)

    @property
    def device_identifier(self) -> str:
        return buf2hex(self._header[4:12])

    @device_identifier.setter
    def device_identifier(self, id: str):
        id = ubinascii.unhexlify(id)
        if len(id) != 8:
            raise ValueError()
        self._header[4:12] = id

    @property
    def packet_flags(self):
        return self._header[3]

    @property
    def multicommand_class(self):
        if self.packet_flags & JD_FRAME_FLAG_IDENTIFIER_IS_SERVICE_CLASS:
            return u32(self._header, 4)

    @property
    def size(self):
        return self._header[12]

    @property
    def requires_ack(self):
        return (self.packet_flags & JD_FRAME_FLAG_ACK_REQUESTED) != 0

    @requires_ack.setter
    def requires_ack(self, val: bool):
        if val != self.requires_ack:
            self._header[3] ^= JD_FRAME_FLAG_ACK_REQUESTED

    @property
    def service_index(self):
        return self._header[13] & JD_SERVICE_INDEX_MASK

    @service_index.setter
    def service_index(self, val: int):
        if val is None:
            raise ValueError("service_index not set")
        self._header[13] = (self._header[13] & JD_SERVICE_INDEX_INV_MASK) | val

    @property
    def crc(self):
        return u16(self._header, 0)

    @property
    def is_event(self):
        return self.is_report and (self.service_command & CMD_EVENT_MASK) != 0

    @property
    def event_code(self):
        if self.is_event:
            return self.service_command & CMD_EVENT_CODE_MASK
        return None

    @property
    def event_counter(self):
        if self.is_event:
            return (self.service_command >> CMD_EVENT_COUNTER_POS) & CMD_EVENT_COUNTER_MASK
        return None

    @property
    def is_reg_set(self):
        return self.service_command >> 12 == CMD_SET_REG >> 12

    @property
    def is_reg_get(self):
        return self.service_command >> 12 == CMD_GET_REG >> 12

    @property
    def reg_code(self):
        return self.service_command & CMD_REG_MASK

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, buf: bytearray):
        if len(buf) > JD_SERIAL_MAX_PAYLOAD_SIZE:
            raise ValueError("Too big")
        self._header[12] = len(buf)
        self._data = buf

    @property
    def is_command(self):
        return (self.packet_flags & JD_FRAME_FLAG_COMMAND) != 0

    @property
    def is_report(self):
        return (self.packet_flags & JD_FRAME_FLAG_COMMAND) == 0

    def to_string(self):
        msg = "{}/{}[{}]: {} sz={}".format(
            self.device_identifier,
            self.service_index,
            self.packet_flags,
            hex_num(self.service_command, 4),
            self.size)
        if self.size < 20:
            msg += ": " + buf2hex(self.data)
        else:
            msg += ": " + buf2hex(self.data[0:20]) + "..."
        return msg

    def __str__(self):
        return "<JDPacket {}>".format(self.to_string())


class EventEmitter:
    def emit(id: str, *args):
        pass


class Bus(EventEmitter):
    def __init__(self) -> None:
        self.devices = []


_JD_CONTROL_ANNOUNCE_FLAGS_RESTART_COUNTER_STEADY = const(0xf)
_QUERY_GC_MS = const(10000)

class Client(EventEmitter):
    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self.broadcast = False
        self.service_class = 0
        self.service_index = 0
        self.current_device: Device = None
        self._queries: list[list[any]] = []

    def _lookup_query(self, code: int, refresh_ms: int):
        idx = 0
        n = now()
        hasold = False
        oldtime = n - _QUERY_GC_MS
        for (data, timestamp, qcode, *_) in self._queries:
            if timestamp < oldtime: hasold = True
            idx += 1
            if code == qcode:
                if timestamp + refresh_ms < n:
                    if data is not None:
                        del self._queries[idx]
                        if hasold: self._gc_queries()
                        return None
                return self._queries[idx]
        if hasold: self._gc_queries()
        return None

    def _gc_queries(self):
        oldtime = now() - _QUERY_GC_MS
        idx = 0
        while idx < len(self._queries):
            _, timestamp, _, *callbacks = self._queries[idx]
            if timestamp < oldtime:
                del self._queries[idx]
                # resume any callbacks - they will get None data, and throw
                for f in callbacks: f()
            else:
                idx += 1

    async def query_register(self, code: int, refresh_ms=500):
        code |= CMD_GET_REG
        query = self._lookup_query(code, refresh_ms)
        if query and query[0]:
            return query[0]
        if query is None:
            query = [None, now(), code]
            # TODO send query
            self._queries.append(query)
        suspend, resume = tasko.suspend()
        query.append(resume)
        await suspend
        if query[0] is None:
            raise RuntimeError("register {0} timeout".format(code))
        return query[0]

    def register_value(self, code: int, refresh_ms=500):
        r = self._lookup_query(code | CMD_GET_REG, refresh_ms)
        if r is None:
            return None
        else:
            return r[0]

    def handle_packet_outer(self, pkt: JDPacket):
        pass


class Device(EventEmitter):
    def __init__(self, bus: Bus, device_id: str, services: bytearray) -> None:
        self.bus = bus
        self.device_id = device_id
        self.services = services
        self.clients: list[Client] = []
        self.last_seen = now()
        self._event_counter: int = None
        bus.devices.append(self)

    @property
    def announce_flags(self):
        return u16(self.services, 0)

    @property
    def reset_count(self):
        return self.announce_flags & _JD_CONTROL_ANNOUNCE_FLAGS_RESTART_COUNTER_STEADY

    @property
    def packet_count(self):
        return self.services[2]

    @property
    def is_connected(self):
        return self.clients != None

    @property
    def short_id(self):
        return self.device_id  # TODO

    def __str__(self) -> str:
        return "<JDDevice {}>".format(self.short_id)

    def service_class_at(self, idx: int):
        if idx == 0:
            return 0
        if idx < 0 or idx >= self.num_service_classes:
            return None
        return u32(self.services, idx << 2)

    @property
    def num_service_classes(self):
        return len(self.services) >> 2

    def process_packet(self, pkt: JDPacket):
        self.last_seen = now()
        self.emit(EV_PACKET_RECEIVE, pkt)

        service_class = self.service_class_at(pkt.service_index)
        if not service_class or service_class == 0xffffffff:
            return

        if pkt.is_event:
            ec = self._event_counter
            if ec is None:
                ec = pkt.event_counter - 1
            ec += 1
            # how many packets ahead and behind current are we?
            ahead = (pkt.event_counter - ec) & CMD_EVENT_COUNTER_MASK
            behind = (ec - pkt.event_counter) & CMD_EVENT_COUNTER_MASK
            # ahead == behind == 0 is the usual case, otherwise
            # behind < 60 means self is an old event (or retransmission of something we already processed)
            # ahead < 5 means we missed at most 5 events, so we ignore self one and rely on retransmission
            # of the missed events, and then eventually the current event
            if ahead > 0 and (behind < 60 or ahead < 5):
                return
            # we got our event
            self.emit(EV_EVENT, pkt)
            self.bus.emit(EV_EVENT, pkt)
            self._event_counter = pkt.event_counter

        client = next(c for c in self.clients if
                      (c.service_class == service_class if c.broadcast else c.service_index == pkt.service_index), None)

        if client:
            # log(`handle pkt at ${client.role} rep=${pkt.serviceCommand}`)
            client.current_device = self
            client.handle_packet_outer(pkt)


"""

    export class Device extends EventSource {
        lastSeen: number
        clients: Client[] = []
        private _event_counter: number
        private _shortId: string
        private queries: RegQuery[]
        _score: number

        matchesRoleAt(role: string, serviceIdx: number) {
            if (!role) return true

            if (role == self.deviceId) return true
            if (role == self.deviceId + ":" + serviceIdx) return true

            return jacdac._rolemgr.getRole(self.deviceId, serviceIdx) == role
        }

        private lookupQuery(reg: number) {
            if (!self.queries) self.queries = []
            return self.queries.find(q => q.reg == reg)
        }

        queryInt(reg: number, refreshRate = 1000) {
            const v = self.query(reg, refreshRate)
            if (!v) return undefined
            return intOfBuffer(v)
        }

        query(reg: number, refreshRate = 1000) {
            let q = self.lookupQuery(reg)
            if (!q) self.queries.push((q = new RegQuery(reg)))

            const now = control.millis()
            if (
                !q.lastQuery ||
                (q.value === undefined && now - q.lastQuery > 500) ||
                (refreshRate != null && now - q.lastQuery > refreshRate)
            ) {
                q.lastQuery = now
                self.sendCtrlCommand(CMD_GET_REG | reg)
            }
            return q.value
        }

        get uptime(): number {
            // create query
            self.query(ControlReg.Uptime, 60000)
            const q = self.lookupQuery(ControlReg.Uptime)
            if (q.value) {
                const up = q.value.getNumber(NumberFormat.UInt32LE, 0)
                const offset = (control.millis() - q.lastReport) * 1000
                return up + offset
            }
            return undefined
        }

        get mcuTemperature(): number {
            return self.queryInt(ControlReg.McuTemperature)
        }

        get firmwareVersion(): string {
            const b = self.query(ControlReg.FirmwareVersion, null)
            if (b) return b.toString()
            else return ""
        }

        get firmwareUrl(): string {
            const b = self.query(ControlReg.FirmwareUrl, null)
            if (b) return b.toString()
            else return ""
        }

        get deviceUrl(): string {
            const b = self.query(ControlReg.DeviceUrl, null)
            if (b) return b.toString()
            else return ""
        }

        handleCtrlReport(pkt: JDPacket) {
            self.lastSeen = control.millis()
            if (pkt.isRegGet) {
                const reg = pkt.regCode
                const q = self.lookupQuery(reg)
                if (q) {
                    q.value = pkt.data
                    q.lastReport = control.millis()
                }
            }
        }

        hasService(service_class: number) {
            const n = self.serviceClassLength
            for (let i = 0; i < n; ++i)
                if (self.serviceClassAt(i) === service_class) return true
            return false
        }

        clientAtServiceIndex(service_index: number) {
            for (const c of self.clients) {
                if (c.device == self && c.service_index == service_index) return c
            }
            return null
        }

        sendCtrlCommand(cmd: number, payload: Buffer = null) {
            const pkt = !payload
                ? JDPacket.onlyHeader(cmd)
                : JDPacket.from(cmd, payload)
            pkt.service_index = JD_SERVICE_INDEX_CTRL
            pkt._sendCmd(self)
        }

        _destroy() {
            log("destroy " + self.shortId)
            for (let c of self.clients) c._detach()
            self.clients = null
        }
    }




ackAwaiters: list[AckAwaiter] = []

        jdunpack<T extends any[]>(fmt: string): T {
            const p = self._data && fmt && jdunpack<T>(self._data, fmt)
            return (p || []) as T
        }

        compress(stripped: Buffer[]) {
            if (stripped.length == 0) return
            let sz = -4
            for (let s of stripped) {
                sz += s.length
            }
            const data = Buffer.create(sz)
            self._header.write(12, stripped[0])
            data.write(0, stripped[0].slice(4))
            sz = stripped[0].length - 4
            for (let s of stripped.slice(1)) {
                data.write(sz, s)
                sz += s.length
            }
            self.data = data
        }

        withFrameStripped() {
            return self._header.slice(12, 4).concat(self._data)
        }

        getNumber(fmt: NumberFormat, offset: number) {
            return self._data.getNumber(fmt, offset)
        }

        jdpack(fmt: string, nums: any[]) {
            self.data = jdpack(fmt, nums)
        }


        _sendCore() {
            if (self._data.length != self._header[12]) throw "jdsize mismatch"
            jacdac.__physSendPacket(self._header, self._data)
            bus.processPacket(self) // handle loop-back packet
        }

        _sendReport(dev: Device) {
            if (!dev) return
            self.deviceIdentifier = dev.deviceId
            self._sendCore()
        }

        _sendCmd(dev: Device) {
            if (!dev) return
            self._sendCmdId(dev.deviceId)
        }

        _sendCmdId(devId: string) {
            if (!devId) return
            self.deviceIdentifier = devId
            self._header[3] |= JD_FRAME_FLAG_COMMAND
            self._sendCore()
        }

        sendAsMultiCommand(service_class: number) {
            self._header[3] |=
                JD_FRAME_FLAG_IDENTIFIER_IS_SERVICE_CLASS |
                JD_FRAME_FLAG_COMMAND
            self._header.setNumber(NumberFormat.UInt32LE, 4, service_class)
            self._header.setNumber(NumberFormat.UInt32LE, 8, 0)
            self._sendCore()
        }

        // returns true when sent and received
        _sendWithAck(devId: string) {
            if (!devId) return false
            self.requiresAck = true
            self._sendCmdId(devId)

            if (!ackAwaiters) {
                ackAwaiters = []
                control.runInParallel(() => {
                    while (1) {
                        pause(Math.randomRange(20, 50))
                        checkAckAwaiters()
                    }
                })
            }

            const aw = new AckAwaiter(self, devId)
            ackAwaiters.push(aw)
            while (aw.nextRetry > 0)
                control.waitForEvent(DAL.DEVICE_ID_NOTIFY, aw.eventId)
            return aw.nextRetry == 0
        }

        static jdpacked(service_command: number, fmt: string, nums: any[]) {
            return JDPacket.from(service_command, jdpack(fmt, nums))
        }

        static segmentData(data: Buffer) {
            if (data.length <= JD_SERIAL_MAX_PAYLOAD_SIZE) return [data]
            const res: Buffer[] = []
            for (let i = 0; i < data.length; i += JD_SERIAL_MAX_PAYLOAD_SIZE)
                res.push(data.slice(i, JD_SERIAL_MAX_PAYLOAD_SIZE))
            return res
        }
    }

    class AckAwaiter {
        nextRetry: number
        numTries = 1
        readonly crc: number
        readonly eventId: number
        constructor(
            public readonly pkt: JDPacket,
            public readonly srcId: string
        ) {
            self.crc = pkt.crc
            self.nextRetry = control.millis() + ACK_DELAY
            self.eventId = control.allocateNotifyEvent()
        }
    }

    function checkAckAwaiters() {
        const now = control.millis()
        const toRetry = ackAwaiters.filter(a => now > a.nextRetry)
        if (!toRetry.length) return
        for (let a of toRetry) {
            if (a.nextRetry == 0) continue // already got ack
            if (a.numTries >= ACK_RETRIES) {
                a.nextRetry = -1
                control.raiseEvent(DAL.DEVICE_ID_NOTIFY, a.eventId)
            } else {
                a.numTries++
                a.nextRetry = now + a.numTries * ACK_DELAY
                a.pkt._sendCore()
            }
        }
        ackAwaiters = ackAwaiters.filter(a => a.nextRetry > 0)
    }

    export function _gotAck(pkt: JDPacket) {
        if (!ackAwaiters) return
        let numNotify = 0
        const srcId = pkt.deviceIdentifier
        const crc = pkt.service_command
        for (let a of ackAwaiters) {
            if (a.crc == crc && a.srcId == srcId) {
                a.nextRetry = 0
                control.raiseEvent(DAL.DEVICE_ID_NOTIFY, a.eventId)
                numNotify++
            }
        }
        if (numNotify) ackAwaiters = ackAwaiters.filter(a => a.nextRetry !== 0)
    }
"""
