import busio
from micropython import const
import time

import tasko

from . import util


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

_JD_READING_THRESHOLD_NEUTRAL = const(0x1)
_JD_READING_THRESHOLD_INACTIVE = const(0x2)
_JD_READING_THRESHOLD_ACTIVE = const(0x3)
_JD_STATUS_CODES_READY = const(0x0)
_JD_STATUS_CODES_INITIALIZING = const(0x1)
_JD_STATUS_CODES_CALIBRATING = const(0x2)
_JD_STATUS_CODES_SLEEPING = const(0x3)
_JD_STATUS_CODES_WAITING_FOR_INPUT = const(0x4)
_JD_STATUS_CODES_CALIBRATION_NEEDED = const(0x64)
_JD_CMD_ANNOUNCE = const(0x0)
_JD_CMD_EVENT = const(0x1)
_JD_CMD_CALIBRATE = const(0x2)
_JD_REG_INTENSITY = const(0x1)
_JD_REG_VALUE = const(0x2)
_JD_REG_MIN_VALUE = const(0x110)
_JD_REG_MAX_VALUE = const(0x111)
_JD_REG_MAX_POWER = const(0x7)
_JD_REG_STREAMING_SAMPLES = const(0x3)
_JD_REG_STREAMING_INTERVAL = const(0x4)
_JD_REG_READING = const(0x101)
_JD_REG_MIN_READING = const(0x104)
_JD_REG_MAX_READING = const(0x105)
_JD_REG_READING_ERROR = const(0x106)
_JD_REG_READING_RESOLUTION = const(0x108)
_JD_REG_INACTIVE_THRESHOLD = const(0x5)
_JD_REG_ACTIVE_THRESHOLD = const(0x6)
_JD_REG_STREAMING_PREFERRED_INTERVAL = const(0x102)
_JD_REG_VARIANT = const(0x107)
_JD_REG_STATUS_CODE = const(0x103)
_JD_REG_INSTANCE_NAME = const(0x109)
_JD_EV_ACTIVE = const(0x1)
_JD_EV_INACTIVE = const(0x2)
_JD_EV_CHANGE = const(0x3)
_JD_EV_STATUS_CODE_CHANGED = const(0x4)
_JD_EV_NEUTRAL = const(0x7)

CMD_GET_REG = const(0x1000)
CMD_SET_REG = const(0x2000)
CMD_TYPE_MASK = const(0xf000)
CMD_REG_MASK = const(0x0fff)
CMD_EVENT_MASK = const(0x8000)
CMD_EVENT_CODE_MASK = const(0xff)
CMD_EVENT_COUNTER_MASK = const(0x7f)
CMD_EVENT_COUNTER_POS = const(8)

EV_CHANGE = "change"
EV_DEVICE_CONNECT = "deviceConnect"
EV_DEVICE_CHANGE = "deviceChange"
EV_DEVICE_ANNOUNCE = "deviceAnnounce"
EV_SELF_ANNOUNCE = "selfAnnounce"
EV_PACKET_PROCESS = "packetProcess"
EV_REPORT_RECEIVE = "reportReceive"
EV_REPORT_UPDATE = "reportUpdate"
EV_RESTART = "restart"
EV_PACKET_RECEIVE = "packetReceive"
EV_EVENT = "packetEvent"
EV_STATUS_EVENT = "statusEvent"
EV_IDENTIFY = "identify"
EV_CONNECTED = "connected"
EV_DISCONNECTED = "disconnected"

_ACK_RETRIES = const(4)
_ACK_DELAY = const(40)

logging = False


def log(msg: str, *args):
    if logging:
        if len(args):
            msg = msg.format(*args)
        print("JD: " + msg)


def now():
    # TODO implement this in C for half-decent precision
    return int(time.monotonic() * 1000)


class JDPacket:
    def __init__(self, *, cmd: int = None, size: int = 0, frombytes: bytes = None, data: bytearray = None) -> None:
        self.timestamp = now()
        if frombytes is None:
            self._header = bytearray(JD_SERIAL_HEADER_SIZE)
            self.data = data or bytearray(size)
        else:
            self._header = bytearray(frombytes[0:JD_SERIAL_HEADER_SIZE])
            self.data = bytearray(frombytes[JD_SERIAL_HEADER_SIZE:])
        if cmd is not None:
            self.service_command = cmd

    @staticmethod
    def packed(cmd: int, fmt: str, *args):
        return JDPacket(cmd=cmd, data=util.pack(fmt, *args))

    def unpack(self, fmt: str):
        return util.unpack(self.data, fmt)

    @property
    def service_command(self):
        return util.u16(self._header, 14)

    @service_command.setter
    def service_command(self, cmd: int):
        util.set_u16(self._header, 14, cmd)

    @property
    def device_identifier(self) -> str:
        return util.buf2hex(self._header[4:12])

    @device_identifier.setter
    def device_identifier(self, id_str: str):
        id = util.hex2buf(id_str)
        if len(id) != 8:
            raise ValueError()
        self._header[4:12] = id

    @property
    def packet_flags(self):
        return self._header[3]

    @property
    def multicommand_class(self):
        if self.packet_flags & JD_FRAME_FLAG_IDENTIFIER_IS_SERVICE_CLASS:
            return util.u32(self._header, 4)

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
        return util.u16(self._header, 0)

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
            util.short_id(self._header[4:12]),
            self.service_index,
            self.packet_flags,
            util.hex_num(self.service_command, 4),
            self.size)
        if self.size < 20:
            msg += ": " + util.buf2hex(self.data)
        else:
            msg += ": " + util.buf2hex(self.data[0:20]) + "..."
        return msg

    def __str__(self):
        return "<JDPacket {}>".format(self.to_string())


def _execute(fn, args):
    async def later():
        if hasattr(fn, "__await__"):
            await fn
        else:
            res = fn(*args)
            if hasattr(res, "__await__"):
                await res
    tasko.add_task(later())


class EventEmitter:
    def emit(self, id: str, *args):
        if not hasattr(self, "_listeners"):
            return
        # copy list before iteration, in case it's modified
        for lid, fn in self._listeners[:]:
            if lid == id:
                _execute(fn, args)

    def _init_emitter(self):
        if not hasattr(self, "_listeners"):
            self._listeners = []

    def on(self, id: str, fn):
        self._init_emitter()
        self._listeners.append((id, fn))

    def off(self, id: str, fn):
        self._init_emitter()
        for i in range(len(self._listeners)):
            id2, fn2 = self._listeners[i]
            if id == id2 and fn is fn2:
                del self._listeners[i]
                return
        raise ValueError("no matching on")

    def once(self, id: str, fn):
        def wrapper(*args):
            self.off(id, wrapper)
            fn(*args)
        self.on(id, wrapper)

    async def event(self, id: str):
        suspend, resume = tasko.suspend()
        self.once(id, resume)
        await suspend


def _service_matches(dev: 'Device', serv: bytearray):
    ds = dev.services
    if not ds or len(ds) != len(serv):
        return False
    for i in range(4, len(serv)):
        if ds[i] != serv[i]:
            return False
    return True


class Bus(EventEmitter):
    def __init__(self, pin) -> None:
        self.devices: list['Device'] = []
        self.unattached_clients: list['Client'] = []
        self.all_clients: list['Client'] = []
        self.servers: list['Server'] = []
        self.busio = busio.JACDAC(pin)
        self.self_device = Device(self, util.buf2hex(self.busio.uid()), bytearray(4))

        from . import ctrl
        ctrls = ctrl.CtrlServer(self)  # attach control server

        async def announce():
            self.emit(EV_SELF_ANNOUNCE)
            self._gc_devices()
            ctrls.queue_announce()
        tasko.schedule(2, announce)

        async def process_packets():
            while True:
                pkt = self.busio.receive()
                if not pkt:
                    break
                self.process_packet(JDPacket(frombytes=pkt))
        tasko.schedule(100, process_packets)

        # async def debug_info():
        #     self.debug_dump()
        # tasko.schedule(0.5, debug_info)

        from . import sample
        sample.acc_sample(self)

    def debug_dump(self):
        print("Devices:")
        for dev in self.devices:
            info = dev.debug_info()
            if dev is self.self_device:
                info = "SELF: " + info
            print(info)
        print("END")

    def _gc_devices(self):
        now_ = now()
        cutoff = now_ - 2000
        self.self_device.last_seen = now_  # make sure not to gc self

        newdevs = []
        for dev in self.devices:
            if dev.last_seen < cutoff:
                dev._destroy()
            else:
                newdevs.append(dev)
        if len(newdevs) != len(self.devices):
            self.devices = newdevs
            self.emit(EV_DEVICE_CHANGE)
            self.emit(EV_CHANGE)

    def _send_core(self, pkt: JDPacket):
        assert len(pkt._data) == pkt._header[12]
        self.busio.send(pkt._header + pkt._data)
        self.process_packet(pkt)  # handle loop-back packet

    def clear_attach_cache(self):
        pass

    def mk_event_cmd(self, ev_code: int):
        if not self._event_counter:
            self._event_counter = 0
        self._event_counter = (self._event_counter +
                               1) & CMD_EVENT_COUNTER_MASK
        assert (ev_code >> 8) == 0
        return (
            CMD_EVENT_MASK |
            (self._event_counter << CMD_EVENT_COUNTER_POS) |
            ev_code
        )

    def _reattach(self, dev: 'Device'):
        dev.last_seen = now()
        log("reattaching services to {}; {}/{} to attach", dev,
            len(self.unattached_clients), len(self.all_clients))
        new_clients = []
        occupied = bytearray(dev.num_service_classes)
        for c in dev.clients:
            if c.broadcast:
                c._detach()
                continue  # will re-attach

            new_class = dev.service_class_at(c.service_index)
            if new_class == c.service_class and dev.matches_role_at(c.role, c.service_index):
                new_clients.append(c)
                occupied[c.service_index] = 1
            else:
                c._detach()

        dev.clients = new_clients
        self.emit(EV_DEVICE_ANNOUNCE, dev)

        if len(self.unattached_clients) == 0:
            return

        for i in range(1, dev.num_service_classes):
            if occupied[i]:
                continue
            service_class = dev.service_class_at(i)
            for cc in self.unattached_clients:
                if cc.service_class == service_class:
                    if cc._attach(dev, i):
                        break

    def process_packet(self, pkt: JDPacket):
        log("route: {}", pkt)
        dev_id = pkt.device_identifier
        multi_command_class = pkt.multicommand_class

        # TODO implement send queue for packet compression

        # if (pkt.requires_ack):
        #     pkt.requires_ack = False  # make sure we only do it once
        #     if pkt.device_identifier == self.self_device.device_id:
        #         ack = JDPacket(cmd=pkt.crc)
        #         ack.service_index = JD_SERVICE_INDEX_CRC_ACK
        #         ack._send_report(self.self_device)

        self.emit(EV_PACKET_PROCESS, pkt)

        if multi_command_class != None:
            if not pkt.is_command:
                return  # only commands supported in multi-command
            for h in self.servers:
                if h.service_class == multi_command_class:
                    # pretend it's directly addressed to us
                    pkt.device_identifier = self.self_device.device_id
                    pkt.service_index = h.service_index
                    h.handle_packet_outer(pkt)
        elif dev_id == self.self_device.device_id and pkt.is_command:
            h = self.servers[pkt.service_index]
            if h:
                # log(`handle pkt at ${h.name} cmd=${pkt.service_command}`)
                h.handle_packet_outer(pkt)
        else:
            if pkt.is_command:
                return  # it's a command, and it's not for us

            dev = None
            try:
                dev = next(d for d in self.devices if d.device_id == dev_id)
            except:
                pass

            if (pkt.service_index == JD_SERVICE_INDEX_CTRL):
                if (pkt.service_command == 0):
                    if (dev and dev.reset_count > (pkt.data[0] & 0xf)):
                        # if the reset counter went down, it means the device reseted;
                        # treat it as new device
                        log("device {} resetted", dev)
                        self.devices.remove(dev)
                        dev._destroy()
                        dev = None
                        self.emit(EV_RESTART)

                    matches = False
                    if not dev:
                        dev = Device(self, pkt.device_identifier, pkt.data)
                        # ask for uptime
                        # dev.send_ctrl_command(CMD_GET_REG | ControlReg.Uptime)
                        self.emit(EV_DEVICE_CONNECT, dev)
                    else:
                        matches = _service_matches(dev, pkt.data)
                        dev.services = pkt.data

                    if not matches:
                        self._reattach(dev)
                if dev:
                    dev.process_packet(pkt)
                return
            elif (pkt.service_index == JD_SERVICE_INDEX_CRC_ACK):
                # _got_ack(pkt)
                pass

            # we can't know the serviceClass,
            # no announcement seen yet for this device
            if not dev:
                return

            dev.process_packet(pkt)


def delayed_callback(seconds, fn):
    async def task():
        await tasko.sleep(seconds)
        fn()
    tasko.add_task(task)


class RawRegisterClient(EventEmitter):
    def __init__(self, client: 'Client', code: int) -> None:
        self.code = code
        self._data: bytearray = None
        self._refreshed_at = 0
        self.client = client

    def current(self, refresh_ms=500):
        if self._refreshed_at + refresh_ms >= now():
            return self._data
        return None

    def _query(self):
        pkt = JDPacket(cmd=(CMD_GET_REG | self.code))
        self.client.send_cmd(pkt)

    def refresh(self):
        prev_data = self._data

        def final_check():
            if prev_data is self._data:
                # if we still didn't get any data, emit "change" event, so that queries can time out
                self._data = None
                self.emit(EV_CHANGE, None)

        def second_refresh():
            if prev_data is self._data:
                self._query()
                delayed_callback(0.100, final_check)

        def first_refresh():
            if prev_data is self._data:
                self._query()
                delayed_callback(0.050, second_refresh)

        self._query()
        delayed_callback(0.020, first_refresh)

    async def query(self, refresh_ms=500):
        curr = self.current(refresh_ms)
        if curr:
            return curr
        self.refresh()
        await self.event(EV_CHANGE)
        if self._data is None:
            raise RuntimeError("Can't read reg #{} (from {})",
                               self.code, self.client)
        return self._data

    def handle_packet(self, pkt: JDPacket):
        if pkt.is_reg_get and pkt.reg_code == self.code:
            self._data = pkt.data
            self.emit(EV_CHANGE, self._data)


class Server(EventEmitter):
    def __init__(self, bus: Bus, service_class: int) -> None:
        self.service_class = service_class
        self.instance_name: str = None
        self.service_index = None
        self.bus = bus
        self._status_code = 0  # u16, u16
        self.service_index = len(self.bus.servers)
        self.bus.servers.append(self)

    def handle_packet(self, pkt: JDPacket):
        pass

    def status_code(self):
        return self._status_code

    def set_status_code(self, code: int, vendor_code: int):
        c = ((code & 0xffff) << 16) | (vendor_code & 0xffff)
        if c != self._status_code:
            self._status_code = c
            self.send_change_event()

    def handle_packet_outer(self, pkt: JDPacket):
        cmd = pkt.service_command
        if cmd == _JD_REG_STATUS_CODE | CMD_GET_REG:
            self.handle_status_code(pkt)
        elif cmd == _JD_REG_INSTANCE_NAME | CMD_GET_REG:
            self.handle_instance_name(pkt)
        else:
            # self.state_updated = False
            self.handle_packet(pkt)

    def handle_packet(self, pkt: JDPacket):
        pass

    def send_report(self, pkt: JDPacket):
        pkt.service_index = self.service_index
        pkt.device_identifier = self.bus.self_device.device_id
        self.bus._send_core(pkt)

    def send_event(self, event_code: int, data: bytearray = None):
        pkt = JDPacket(cmd=self.bus.mk_event_cmd(event_code), data=data)
        def resend(): self.send_report(pkt)
        resend()
        delayed_callback(0.020, resend)
        delayed_callback(0.100, resend)

    def send_change_event(self):
        self.send_event(_JD_EV_CHANGE)
        self.emit(EV_CHANGE)

    def handle_status_code(self, pkt: JDPacket):
        self.handle_reg_u32(pkt, _JD_REG_STATUS_CODE, self._status_code)

    def handle_reg_u32(self, pkt: JDPacket, register: int, current: int):
        return self.handle_reg(pkt, register, "I", current)

    def handle_reg_i32(self, pkt: JDPacket, register: int, current: int):
        return self.handle_reg(pkt, register, "i", current)

    def handle_reg(self, pkt: JDPacket, register: int, fmt: str, current):
        getset = pkt.service_command >> 12
        if getset == 0 or getset > 2:
            return current
        reg = pkt.service_command & 0xfff
        if reg != register:
            return current
        if getset == 1:
            self.send_report(JDPacket.packed(
                pkt.service_command, fmt, current))
        else:
            if register >> 8 == 0x1:
                return current  # read-only
            v = pkt.unpack(fmt)
            if not isinstance(current, tuple):
                v = v[0]
            if v != current:
                self.state_updated = True
                current = v
        return current

    def handle_instance_name(self, pkt: JDPacket):
        self.send_report(JDPacket(cmd=pkt.service_command,
                         data=bytearray(self.instance_name, "utf-8")))

    def log(self, text: str, *args):
        prefix = "{}.{}>".format(self.bus.self_device,
                                 self.instance_name or self.service_index)
        log(prefix + text, *args)


class Client(EventEmitter):
    def __init__(self, bus: Bus, service_class: int, role: str) -> None:
        self.bus = bus
        self.broadcast = False
        self.service_class = service_class
        self.service_index = None
        self.device: 'Device' = None
        self.current_device: 'Device' = None
        self.role = role
        self._registers: list[RawRegisterClient] = []
        bus.unattached_clients.append(self)
        bus.all_clients.append(self)

    def _lookup_register(self, code: int):
        for reg in self._registers:
            if reg.code == code:
                return reg
        return None

    def register(self, code: int):
        r = self._lookup_register(code)
        if r is None:
            r = RawRegisterClient(self, code)
            self._registers.append(r)
        return r

    def handle_packet(self, pkt: JDPacket):
        pass

    def handle_packet_outer(self, pkt: JDPacket):
        if pkt.is_reg_get:
            r = self._lookup_register(pkt.reg_code)
            if r is not None:
                r.handle_packet(pkt)
        if pkt.is_event:
            self.emit(EV_EVENT, pkt)
        self.handle_packet(pkt)

    def send_cmd(self, pkt: JDPacket):
        if self.current_device is None:
            return
        pkt.service_index = self.service_index
        pkt.device_identifier = self.current_device.device_id
        pkt._header[3] |= JD_FRAME_FLAG_COMMAND
        self.bus._send_core(pkt)

    def on_attach(self):
        pass

    def _attach(self, dev: 'Device', service_idx: int):
        assert self.device is None
        if not self.broadcast:
            if not dev.matches_role_at(self.role, service_idx):
                return False
            self.device = dev
            self.service_index = service_idx
            self.bus.unattached_clients.remove(self)
        log("attached {}/{} to client {}", dev, service_idx, self.role)
        dev.clients.append(self)
        self.emit(EV_CONNECTED)
        return True

    def _detach(self):
        log("detached {}", self.role)
        self.service_index = None
        if not self.broadcast:
            assert self.device
            self.device = None
            self.bus.unattached_clients.append(self)
            self.bus.clear_attach_cache()
        self.emit(EV_DISCONNECTED)


_JD_CONTROL_ANNOUNCE_FLAGS_RESTART_COUNTER_STEADY = const(0xf)


class Device(EventEmitter):
    def __init__(self, bus: Bus, device_id: str, services: bytearray) -> None:
        self.bus = bus
        self.device_id = device_id
        self.services = services
        self.clients: list[Client] = []
        self.last_seen = now()
        self._event_counter: int = None
        self._ctrl_client: Client = None
        bus.devices.append(self)

    @property
    def ctrl_client(self):
        if self._ctrl_client is None:
            self._ctrl_client = Client(self.bus, 0, "")
            self._ctrl_client._attach(self, 0)
        return self._ctrl_client

    @property
    def announce_flags(self):
        return util.u16(self.services, 0)

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
        return util.short_id(self.device_id)

    def __str__(self) -> str:
        return "<JDDevice {}>".format(self.short_id)

    def debug_info(self):
        r = "Device: " + self.short_id + "; "
        for i in range(self.num_service_classes):
            r += util.hex_num(self.service_class_at(i)) + ", "
        return r

    def service_class_at(self, idx: int):
        if idx == 0:
            return 0
        if idx < 0 or idx >= self.num_service_classes:
            return None
        return util.u32(self.services, idx << 2)

    def matches_role_at(self, role: str, service_idx: int):
        if not role or role == self.device_id or role == "{}:{}".format(self.device_id, service_idx):
            return True
        return True
        # return jacdac._rolemgr.getRole(self.deviceId, serviceIdx) == role

    @property
    def num_service_classes(self):
        return len(self.services) >> 2

    def _destroy(self):
        log("destroy " + self.short_id)
        for c in self.clients:
            c._detach()
        self.clients = None

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

        for c in self.clients:
            if (c.broadcast and c.service_class == service_class) or \
               (not c.broadcast and c.service_index == pkt.service_index):
                # log(`handle pkt at ${client.role} rep=${pkt.serviceCommand}`)
                c.current_device = self
                c.handle_packet_outer(pkt)
