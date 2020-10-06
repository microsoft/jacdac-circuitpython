from jacdac import JDStack, JDAccelerometer
import time
import adafruit_lsm6ds.lsm6ds33
import board

jd = JDStack(board.P12)
i2c = board.I2C()
accelerometer = adafruit_lsm6ds.lsm6ds33.LSM6DS33(i2c)
jd_accel = JDAccelerometer(accelerometer, jd)
jd.add_service(jd_accel)


while True:
    jd.process()
    time.sleep(.01)