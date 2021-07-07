from busio import JACDAC
import time
import struct
import microcontroller
import supervisor

JD_FRAME_HEADER_SIZE = 12
JD_FRAME_FLAG_COMMAND = 0x01
JD_FRAME_FLAG_ACK_REQUESTED = 0x02
JD_FRAME_FLAG_IDENTIFIER_IS_SERVICE_CLASS = 0x04

JD_PACKET_HEADER_SIZE = 4
REG_INTENSITY = 0x01

REG_VALUE = 0x02
REG_STREAMING_SAMPLES = 0x03
REG_STREAMING_INTERVAL = 0x04
REG_LOW_THRESHOLD = 0x05
REG_HIGH_THRESHOLD = 0x06
REG_MAX_POWER = 0x07
REG_READING = 0x101

CMD_GET_REG = 0x1000
CMD_SET_REG = 0x2000
CMD_TYPE_MASK = 0xf000
CMD_VAL_MASK = 0x0fff

CMD_ADVERTISEMENT_DATA = 0x00
CMD_EVENT = 0x01
CMD_CALIBRATE = 0x02
CMD_GET_DESCRIPTION = 0x03
CMD_CTRL_NOOP = 0x80
CMD_CTRL_IDENTIFY = 0x81
CMD_CTRL_RESET = 0x82

REG_CTRL_DEVICE_DESCRIPTION = 0x180
REG_CTRL_DEVICE_CLASS = 0x181
REG_CTRL_TEMPERATURE = 0x182
REG_CTRL_FIRMWARE_VERSION = 0x185
REG_CTRL_MICROS_SINCE_BOOT = 0x186

jacdac_instance = None

class JDHeader:
    data = None
    crc = 0
    size = 0
    flags = 0
    device_id = 0

    def __init__(self, buf):
        self.data = buf
        if self.data is not None:
            self.crc, self.size, self.flags, self.device_id = struct.unpack_from('<HBBQ', self.data, 0)

    def serialize(self):
        b = bytearray(12)
        struct.pack_into('<HBBQ', b, 0, 0, self.size, self.flags, self.device_id) # blank crc, computed by phys
        return b


class JDPacket:
    header = None
    data = None
    size = None
    service_index = None
    service_command = None

    def __init__(self, header, data):
        self.header = header

        if self.header is None:
            self.header = JDHeader(None)

        if data is not None:
            upack = struct.unpack_from('<BBH', data, 0)
            self.size = upack[0]
            self.service_index = upack[1]
            self.service_command = upack[2]
            self.data = data[4:]

    def is_reg_set(self):
        return (self.service_command >> 12) == (CMD_SET_REG >> 12)

    def is_reg_get(self):
        return (self.service_command >> 12) == (CMD_GET_REG >> 12)

    def is_command(self):
        if self.data is None:
            return False

        return not (self.header.flags & JD_FRAME_FLAG_COMMAND) == 0

    def is_register(self):
        if self.data is None:
            return False

        return (self.header.flags & JD_FRAME_FLAG_COMMAND) == 0

    def serialize(self):
        b = bytearray(4)
        struct.pack_into('<BBH', b, 0, len(self.data), self.service_index, self.service_command)
        return self.header.serialize() + b + self.data


class JDServiceHost:
    service_index = None
    service_class = None
    time = 0
    stack = None
    def __init__(self, service_class, stack):
        self.service_class = service_class
        self.time = time.monotonic()
        self.stack = stack

    def handle_packet(self, p):
        if p.is_command():
            self.handle_command(p)
        else:
            self.handle_report(p)

    def handle_report(self, p):
        return

    def handle_command(self, p):
        if p.is_reg_set():
            self.handle_register_set(p)
        else:
            self.handle_register_get(p)

    def handle_register_set(self, p):
        return

    def handle_register_get(self, p):
        return

    def send_report(self, cmd, data):
        resp = JDPacket(None, None)
        resp.service_command = cmd
        resp.service_index = self.service_index
        resp.data = data
        self.stack.send_report(resp)

    def tick(self, now):
        return


class JDControl(JDServiceHost):
    stack = None
    def __init__(self, stack):
        super().__init__(0, stack) # control is service class 0

    def handle_command(self, p):
        cmd = p.service_command & CMD_VAL_MASK
        resp = JDPacket(None, None)
        resp.service_index = 0

        if cmd == CMD_CTRL_RESET:
            supervisor.reload()
        elif cmd == REG_CTRL_DEVICE_DESCRIPTION:
            resp.service_command = CMD_GET_REG | REG_CTRL_DEVICE_DESCRIPTION
            resp.data = bytearray("Generic CircuitPython device")
            self.stack.send(resp)
        elif cmd == REG_CTRL_DEVICE_CLASS:
            resp.service_command = CMD_GET_REG | REG_CTRL_DEVICE_CLASS
            resp.data = bytearray(4)
            struct.pack_into("<I", resp.data, 0, 0xAAAAAAAA)
            self.stack.send(resp)
        elif cmd == REG_CTRL_FIRMWARE_VERSION:
            resp.service_command = CMD_GET_REG | REG_CTRL_FIRMWARE_VERSION
            resp.data = bytearray("v0.0.1")
            self.stack.send(resp)

    def tick(self, now):
        if now - self.time < .5:
            return

        self.time = now

        adv = JDPacket(None, None)
        adv.service_index = 0
        adv.service_command = 0
        adv.data = bytearray(len(self.stack.services) * 4)

        i = 0
        for s in self.stack.services:
            struct.pack_into('<I', adv.data, i, s.service_class)
            i += 4

        self.stack.send(adv)

class JDDevice:
    last_packet = None
    ticks = 5
    service_classes = None
    device_id = None
    short_id = None
    time = 0

    def __init__(self, packet, short_id):
        if packet is not None:
            self.device_id = packet.header.device_id
            self.short_id = short_id
            self.update(packet)
            self.time = time.monotonic()

    def update(self, packet):
        self.ticks = 5
        self.service_classes = struct.unpack_from('<' + ("I" * int(packet.size/4)), packet.data, 0)

    def tick(self, t):
        if self.time == 0:
            return False

        if t - self.time >= .5:
            self.ticks -= 1

        return self.ticks == 0

class JDSensor(JDServiceHost):
    streaming = -1
    streaming_interval = .1

    def __init__(self, service_class, stack):
        super().__init__(service_class, stack)

    def tick(self, now):
        if self.streaming >= 0 and (now - self.time) >= self.streaming_interval:
            self.time = now
            self.streaming -= 1
            self.__sensor_report()

    def handle_register_set(self, p):
        cmd = p.service_command & CMD_VAL_MASK
        if cmd == REG_STREAMING_SAMPLES:
            self.streaming = struct.unpack_from('<B',p.data, 0)[0]
        if cmd == REG_STREAMING_INTERVAL:
            self.streaming_interval = float(struct.unpack_from('<I',p.data, 0)[0]) / 1000

    def handle_register_get(self, p):
        cmd = p.service_command & CMD_VAL_MASK
        if cmd == REG_STREAMING_SAMPLES:
            b = bytearray(1)
            val = 0
            if self.streaming > 0:
                val = self.streaming
            struct.pack_into('<B', b, 0, val)
            self.send_report(CMD_GET_REG | REG_STREAMING_SAMPLES, b)

        if cmd == REG_STREAMING_INTERVAL:
            resp = JDPacket(None, None)
            b = bytearray(4)
            struct.pack_into('<I', b, 0, int(self.streaming_interval * 1000))
            self.send_report(CMD_GET_REG | REG_STREAMING_INTERVAL, b)


class JDAccelerometer(JDSensor):
    accelerometer = None
    def __init__(self, accelerometer, stack):
        super().__init__(0x1f140409, stack)
        self.accelerometer = accelerometer

    def __sensor_report(self):
        p = JDPacket(None, None)
        b = bytearray(6) # 3 sixteen bit samples
        raw = self.accelerometer._raw_accel_data
        struct.pack_into('<hhh', b, 0, raw[0], raw[1], raw[2])
        self.send_report(CMD_GET_REG | REG_READING, b)

    def handle_register_get(self, p):
        super().handle_register_get(p)
        cmd = p.service_command & CMD_VAL_MASK
        if cmd == 0x101:
            self.__sensor_report()

class JDStack:
    bus = None
    dev = None
    ctrl = None
    buf = bytearray(256)
    services = []
    devices = []
    udid = 0

    def __init__(self, pin):
        jacdac_instance = self
        self.bus = JACDAC(pin)
        self.ctrl = JDControl(self)
        self.services = [self.ctrl]

        self.dev = JDDevice(None, None)
        self.dev.device_id = struct.unpack_from('<Q',microcontroller.cpu.uid,0)[0]
        self.dev.short_id = self.bus.hash(microcontroller.cpu.uid).decode()
        self.dev.ticks = -1

        self.devices += [self.dev]

    ####
    # send a packet without any modifications by the stack
    ####
    def send(self, packet, device_id = None):
        if device_id:
            packet.header.device_id = device_id
        else:
            packet.header.device_id = self.dev.device_id
        packet.header.size = len(packet.data) + JD_PACKET_HEADER_SIZE
        self.bus.send(packet.serialize())

    ####
    # send a command packet
    ####
    def send_command(self, packet, device_id = None):
        if device_id:
            packet.header.device_id = device_id
        else:
            packet.header.device_id = self.dev.device_id
        packet.header.flags |= JD_FRAME_FLAG_COMMAND
        packet.header.size = len(packet.data) + JD_PACKET_HEADER_SIZE
        self.bus.send(packet.serialize())

    ####
    # send a report packet
    ####
    def send_report(self, packet, device_id = None):
        if device_id:
            packet.header.device_id = device_id
        else:
            packet.header.device_id = self.dev.device_id
        packet.header.size = len(packet.data) + JD_PACKET_HEADER_SIZE
        self.bus.send(packet.serialize())

    def add_service(self, service):
        #todo: in future we may want to have differentiation between client/host services
        self.services += [service]
        service.service_index = len(self.services) - 1

    def process(self):
        p = self.bus.receive(self.buf)

        packets = []

        while p:
            header = JDHeader(self.buf[:JD_FRAME_HEADER_SIZE])
            i = JD_FRAME_HEADER_SIZE

            while i < JD_FRAME_HEADER_SIZE + header.size:

                size = struct.unpack_from('B', self.buf, i)[0]
                packets += [JDPacket(header, bytearray(self.buf[i: i + size + JD_PACKET_HEADER_SIZE]))]
                i += size + JD_PACKET_HEADER_SIZE

            p = self.bus.receive(self.buf)

        for p in packets:
            if p.header.device_id == self.dev.device_id and p.service_index < len(self.services):
                self.services[p.service_index].handle_packet(p)
            elif p.service_index == 0 and p.service_command == CMD_ADVERTISEMENT_DATA:
                found = None
                for d in self.devices:
                    if d.device_id == p.header.device_id:
                        found = d
                        break
                if found is None:
                    self.devices += [JDDevice(p, self.bus.hash(p.header.data[4:12]).decode())]
                else:
                    found.update(p)

        now = time.monotonic()

        for s in self.services:
            s.tick(now)

        for d in self.devices:
            if d.tick(now):
                self.devices.remove(d)

