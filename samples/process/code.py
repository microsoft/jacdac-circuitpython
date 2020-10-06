from jacdac import JDStack
import board
import time

jd = JDStack(board.P12)

while True:
    jd.process()
    time.sleep(.01)