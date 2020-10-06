from jacdac import JDStack
import board
import displayio
import time
import terminalio
from adafruit_display_text.label import Label

disp = board.DISPLAY
jd = JDStack(board.P12)

known_services = {
    0x1d90e1c5:"aggregator",
    0x1f140409:"accelerometer"
}

while True:
    dlist = displayio.Group()

    row = 1
    for device in jd.devices:
        sid = str(device.short_id)
        if idx == 0:
            sid += " <self>"

        dlabel = Label(terminalio.FONT, text=sid, color=0x0000FF)
        dlabel.x = 10
        dlabel.y = row * 10
        dlist.append(dlabel)

        if idx > 0:
            sinfo = Label(terminalio.FONT, text=[known_services[s] for s in device.service_classes[1:] if s in known_services.keys()], color=0x0000FF)
            dlabel.x = 10
            dlabel.y = (row + 1) * 20
            dlist.append(sinfo)

        row += 2

    disp.show(dlist)

    jd.process()
    time.sleep(.01)