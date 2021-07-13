import board
import digitalio
import time
import gc

def mem(lbl):
    gc.collect()
    print(lbl, gc.mem_alloc())

q = digitalio.DigitalInOut(board.IO26)
q.pull = digitalio.Pull.UP
print("")
if not q.value:
    print("skipping auto-start")
else:
    print("auto-start normal")
    lim = digitalio.DigitalInOut(board.ILIM_EN)
    limf = digitalio.DigitalInOut(board.ILIM_FAULT)
    lim.switch_to_output()
    lim.value = False # enable limiter
    limf.switch_to_output()
    limf.value = True
    time.sleep(0.001)
    limf.switch_to_input()
    import jacdac
    jacdac.Bus(board.JACDAC)
    import tasko
    tasko.run()
