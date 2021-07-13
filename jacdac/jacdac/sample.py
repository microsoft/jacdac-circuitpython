from . import *

_JD_SERVICE_CLASS_BUTTON = const(0x1473a263)
_JD_BUTTON_REG_PRESSURE = const(0x101)
_JD_BUTTON_REG_ANALOG = const(0x180)
_JD_BUTTON_REG_PRESSED = const(0x181)
_JD_BUTTON_EV_DOWN = const(0x1)
_JD_BUTTON_EV_UP = const(0x2)
_JD_BUTTON_EV_HOLD = const(0x81)

_JD_SERVICE_CLASS_ACCELEROMETER = const(0x1f140409)
_JD_ACCELEROMETER_REG_FORCES = const(0x101)
_JD_ACCELEROMETER_REG_FORCES_ERROR = const(0x106)
_JD_ACCELEROMETER_REG_MAX_FORCE = const(0x80)
_JD_ACCELEROMETER_EV_TILT_UP = const(0x81)
_JD_ACCELEROMETER_EV_TILT_DOWN = const(0x82)
_JD_ACCELEROMETER_EV_TILT_LEFT = const(0x83)
_JD_ACCELEROMETER_EV_TILT_RIGHT = const(0x84)
_JD_ACCELEROMETER_EV_FACE_UP = const(0x85)
_JD_ACCELEROMETER_EV_FACE_DOWN = const(0x86)
_JD_ACCELEROMETER_EV_FREEFALL = const(0x87)
_JD_ACCELEROMETER_EV_SHAKE = const(0x8b)
_JD_ACCELEROMETER_EV_FORCE_2G = const(0x8c)
_JD_ACCELEROMETER_EV_FORCE_3G = const(0x88)
_JD_ACCELEROMETER_EV_FORCE_6G = const(0x89)
_JD_ACCELEROMETER_EV_FORCE_8G = const(0x8a)


def acc_sample(bus: Bus):
    acc = Client(bus, _JD_SERVICE_CLASS_ACCELEROMETER, "acc")

    async def acc_ev(pkt: JDPacket):
        print("acc", pkt.event_code)
        v = await acc.register(_JD_ACCELEROMETER_REG_FORCES).query()
        print(v)
    acc.on(EV_EVENT, acc_ev)

    btn = Client(bus, _JD_SERVICE_CLASS_BUTTON, "btn")

    async def btn_ev(pkt: JDPacket):
        print("btn", pkt.event_code, len(pkt.data) and pkt.unpack("I"))
        v = await btn.register(13).query()
        print(v)
    btn.on(EV_EVENT, btn_ev)
