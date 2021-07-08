import time
import microcontroller
from micropython import const

from . import *

_JD_SERVICE_CLASS_CONTROL = const(0x0)
_JD_CONTROL_ANNOUNCE_FLAGS_RESTART_COUNTER_STEADY = const(0xf)
_JD_CONTROL_ANNOUNCE_FLAGS_RESTART_COUNTER1 = const(0x1)
_JD_CONTROL_ANNOUNCE_FLAGS_RESTART_COUNTER2 = const(0x2)
_JD_CONTROL_ANNOUNCE_FLAGS_RESTART_COUNTER4 = const(0x4)
_JD_CONTROL_ANNOUNCE_FLAGS_RESTART_COUNTER8 = const(0x8)
_JD_CONTROL_ANNOUNCE_FLAGS_STATUS_LIGHT_NONE = const(0x0)
_JD_CONTROL_ANNOUNCE_FLAGS_STATUS_LIGHT_MONO = const(0x10)
_JD_CONTROL_ANNOUNCE_FLAGS_STATUS_LIGHT_RGB_NO_FADE = const(0x20)
_JD_CONTROL_ANNOUNCE_FLAGS_STATUS_LIGHT_RGB_FADE = const(0x30)
_JD_CONTROL_ANNOUNCE_FLAGS_SUPPORTS_ACK = const(0x100)
_JD_CONTROL_ANNOUNCE_FLAGS_SUPPORTS_BROADCAST = const(0x200)
_JD_CONTROL_ANNOUNCE_FLAGS_SUPPORTS_FRAMES = const(0x400)
_JD_CONTROL_ANNOUNCE_FLAGS_IS_CLIENT = const(0x800)
_JD_CONTROL_CMD_SERVICES = const(0)
_JD_CONTROL_CMD_NOOP = const(0x80)
_JD_CONTROL_CMD_IDENTIFY = const(0x81)
_JD_CONTROL_CMD_RESET = const(0x82)
_JD_CONTROL_CMD_FLOOD_PING = const(0x83)
_JD_CONTROL_CMD_SET_STATUS_LIGHT = const(0x84)
_JD_CONTROL_REG_RESET_IN = const(0x80)
_JD_CONTROL_REG_DEVICE_DESCRIPTION = const(0x180)
_JD_CONTROL_REG_FIRMWARE_IDENTIFIER = const(0x181)
_JD_CONTROL_REG_BOOTLOADER_FIRMWARE_IDENTIFIER = const(0x184)
_JD_CONTROL_REG_FIRMWARE_VERSION = const(0x185)
_JD_CONTROL_REG_MCU_TEMPERATURE = const(0x182)
_JD_CONTROL_REG_UPTIME = const(0x186)
_JD_CONTROL_REG_DEVICE_URL = const(0x187)
_JD_CONTROL_REG_DEVICE_SPECIFICATION_URL = const(0x189)
_JD_CONTROL_REG_FIRMWARE_URL = const(0x188)


class CtrlServer(Server):
    def __init__(self, bus: Bus) -> None:
        super().__init__(bus, 0)
        self.restart_counter = 0

    def queue_announce(self):
        log("announce: %d " % self.restart_counter)
        self.restart_counter += 1
        ids = [s.service_class for s in self.bus. servers]
        rest = self.restart_counter
        if rest > 0xf:
            rest = 0xf
        ids[0] = (
            rest |
            _JD_CONTROL_ANNOUNCE_FLAGS_IS_CLIENT |
            _JD_CONTROL_ANNOUNCE_FLAGS_SUPPORTS_ACK |
            _JD_CONTROL_ANNOUNCE_FLAGS_SUPPORTS_BROADCAST |
            _JD_CONTROL_ANNOUNCE_FLAGS_SUPPORTS_FRAMES
        )
        buf = util.pack("%dI" % len(ids), ids)
        self.send_report(JDPacket(cmd=0, data=buf))

        # auto bind
        # if jacdac.role_manager_server.auto_bind:
        #     self.auto_bind_cnt++
        #     # also, only do it every two announces (TBD)
        #     if self.auto_bind_cnt >= 2:
        #         self.auto_bind_cnt = 0
        #         jacdac.role_manager_server.bind_roles()

    # def handle_flood_ping(self, pkt: JDPacket):
    #     num_responses, counter, size = pkt.unpack("IIB")
    #     payload = bytearray(4 + size)
    #     for i in range(size): payload[4+i]=i
    #     def queue_ping():
    #         if num_responses <= 0:
    #             control.internal_on_event(
    #                 jacdac.__physId(),
    #                 EVT_TX_EMPTY,
    #                 do_nothing
    #             )
    #         else:
    #             payload.set_number(NumberFormat.UInt32LE, 0, counter)
    #             self.send_report(
    #                 JDPacket.from(ControlCmd.FloodPing, payload)
    #             )
    #             num_responses--
    #             counter++
    #     control.internal_on_event(jacdac.__physId(), EVT_TX_EMPTY, queue_ping)
    #     queue_ping()

    def handle_packet(self, pkt: JDPacket):
        if pkt.is_reg_get:
            if pkt.reg_code == _JD_CONTROL_REG_UPTIME:
                self.send_report(JDPacket.packed(
                    CMD_GET_REG | _JD_CONTROL_REG_UPTIME, "Q",  time.monotonic_ns() // 1000))
        else:
            cmd = pkt.service_command
            if cmd == _JD_CONTROL_CMD_SERVICES:
                self.queue_announce()
            elif cmd == _JD_CONTROL_CMD_IDENTIFY:
                self.log("identify")
                self.bus.emit(EV_IDENTIFY)
            elif cmd == _JD_CONTROL_CMD_RESET:
                microcontroller.reset()
