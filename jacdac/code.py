import board
import digitalio
import time

q = digitalio.DigitalInOut(board.IO1)
q.pull = digitalio.Pull.UP
print("")
if not q.value:
    print("skipping auto-start")
else:
    print("auto-start normal")
    import jacdac
    jacdac.Bus(board.IO18)
    import tasko
    tasko.run()
