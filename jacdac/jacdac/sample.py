from . import *

_JD_SERVICE_CLASS_BUTTON = const(0x1473a263)
_JD_BUTTON_REG_PRESSURE = const(0x101)
_JD_BUTTON_REG_ANALOG = const(0x180)
_JD_BUTTON_REG_PRESSED = const(0x181)
_JD_BUTTON_EV_DOWN = const(0x1)
_JD_BUTTON_EV_UP = const(0x2)
_JD_BUTTON_EV_HOLD = const(0x81)

def acc_sample(bus:Bus):
    btn = Client(bus, _JD_SERVICE_CLASS_BUTTON, "btn")
    def btn_ev(pkt: JDPacket):
        print("btn", pkt.event_code)
    btn.on(EV_EVENT, btn_ev)
