from busio import JACDAC
from micropython import const
import time
import struct
import microcontroller
import supervisor
import ubinascii

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


class JDPacket:
    def __init__(self, *, cmd: int = None, size: int = 0, frombytes: bytes = None) -> None:
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


class Bus:
    def __init__(self) -> None:
        self.devices = []


_JD_CONTROL_ANNOUNCE_FLAGS_RESTART_COUNTER_STEADY = const(0xf)


class Device:
    def __init__(self, bus: Bus, device_id: str, services: bytearray) -> None:
        self.bus = bus
        self.device_id = device_id
        self.services = services
        self.clients = []
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


"""

    export class Device extends EventSource {
        lastSeen: number
        clients: Client[] = []
        private _eventCounter: number
        private _shortId: string
        private queries: RegQuery[]
        _score: number

        get isConnected() {
            return this.clients != null
        }

        get shortId() {
            // TODO measure if caching is worth it
            if (!this._shortId) this._shortId = shortDeviceId(this.deviceId)
            return this._shortId
        }

        toString() {
            return this.shortId
        }

        matchesRoleAt(role: string, serviceIdx: number) {
            if (!role) return true

            if (role == this.deviceId) return true
            if (role == this.deviceId + ":" + serviceIdx) return true

            return jacdac._rolemgr.getRole(this.deviceId, serviceIdx) == role
        }

        private lookupQuery(reg: number) {
            if (!this.queries) this.queries = []
            return this.queries.find(q => q.reg == reg)
        }

        get serviceClassLength() {
            return this.services.length >> 2
        }

        serviceClassAt(serviceIndex: number) {
            return serviceIndex == 0
                ? 0
                : this.services.getNumber(
                      NumberFormat.UInt32LE,
                      serviceIndex << 2
                  )
        }

        queryInt(reg: number, refreshRate = 1000) {
            const v = this.query(reg, refreshRate)
            if (!v) return undefined
            return intOfBuffer(v)
        }

        query(reg: number, refreshRate = 1000) {
            let q = this.lookupQuery(reg)
            if (!q) this.queries.push((q = new RegQuery(reg)))

            const now = control.millis()
            if (
                !q.lastQuery ||
                (q.value === undefined && now - q.lastQuery > 500) ||
                (refreshRate != null && now - q.lastQuery > refreshRate)
            ) {
                q.lastQuery = now
                this.sendCtrlCommand(CMD_GET_REG | reg)
            }
            return q.value
        }

        get uptime(): number {
            // create query
            this.query(ControlReg.Uptime, 60000)
            const q = this.lookupQuery(ControlReg.Uptime)
            if (q.value) {
                const up = q.value.getNumber(NumberFormat.UInt32LE, 0)
                const offset = (control.millis() - q.lastReport) * 1000
                return up + offset
            }
            return undefined
        }

        get mcuTemperature(): number {
            return this.queryInt(ControlReg.McuTemperature)
        }

        get firmwareVersion(): string {
            const b = this.query(ControlReg.FirmwareVersion, null)
            if (b) return b.toString()
            else return ""
        }

        get firmwareUrl(): string {
            const b = this.query(ControlReg.FirmwareUrl, null)
            if (b) return b.toString()
            else return ""
        }

        get deviceUrl(): string {
            const b = this.query(ControlReg.DeviceUrl, null)
            if (b) return b.toString()
            else return ""
        }

        processPacket(pkt: JDPacket) {
            this.lastSeen = control.millis()
            this.emit(PACKET_RECEIVE, pkt)

            const serviceClass = this.serviceClassAt(pkt.serviceIndex)
            if (!serviceClass || serviceClass == 0xffffffff) return

            if (pkt.isEvent) {
                let ec = this._eventCounter
                if (ec === undefined) ec = pkt.eventCounter - 1
                ec++
                // how many packets ahead and behind current are we?
                const ahead = (pkt.eventCounter - ec) & CMD_EVENT_COUNTER_MASK
                const behind = (ec - pkt.eventCounter) & CMD_EVENT_COUNTER_MASK
                // ahead == behind == 0 is the usual case, otherwise
                // behind < 60 means this is an old event (or retransmission of something we already processed)
                // ahead < 5 means we missed at most 5 events, so we ignore this one and rely on retransmission
                // of the missed events, and then eventually the current event
                if (ahead > 0 && (behind < 60 || ahead < 5)) return
                // we got our event
                this.emit(EVENT, pkt)
                bus.emit(EVENT, pkt)
                this._eventCounter = pkt.eventCounter
            }

            const client = this.clients.find(c =>
                c.broadcast
                    ? c.serviceClass == serviceClass
                    : c.serviceIndex == pkt.serviceIndex
            )
            if (client) {
                // log(`handle pkt at ${client.role} rep=${pkt.serviceCommand}`)
                client.currentDevice = this
                client.handlePacketOuter(pkt)
            }
        }

        handleCtrlReport(pkt: JDPacket) {
            this.lastSeen = control.millis()
            if (pkt.isRegGet) {
                const reg = pkt.regCode
                const q = this.lookupQuery(reg)
                if (q) {
                    q.value = pkt.data
                    q.lastReport = control.millis()
                }
            }
        }

        hasService(serviceClass: number) {
            const n = this.serviceClassLength
            for (let i = 0; i < n; ++i)
                if (this.serviceClassAt(i) === serviceClass) return true
            return false
        }

        clientAtServiceIndex(serviceIndex: number) {
            for (const c of this.clients) {
                if (c.device == this && c.serviceIndex == serviceIndex) return c
            }
            return null
        }

        sendCtrlCommand(cmd: number, payload: Buffer = null) {
            const pkt = !payload
                ? JDPacket.onlyHeader(cmd)
                : JDPacket.from(cmd, payload)
            pkt.serviceIndex = JD_SERVICE_INDEX_CTRL
            pkt._sendCmd(this)
        }

        _destroy() {
            log("destroy " + this.shortId)
            for (let c of this.clients) c._detach()
            this.clients = null
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
            bus.processPacket(this) // handle loop-back packet
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

        sendAsMultiCommand(serviceClass: number) {
            self._header[3] |=
                JD_FRAME_FLAG_IDENTIFIER_IS_SERVICE_CLASS |
                JD_FRAME_FLAG_COMMAND
            self._header.setNumber(NumberFormat.UInt32LE, 4, serviceClass)
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

            const aw = new AckAwaiter(this, devId)
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
