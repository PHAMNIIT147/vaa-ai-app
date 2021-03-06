from PyQt5.QtCore import QThread, QMutex, QTime, qDebug, QMutexLocker, pyqtSignal
from PyQt5.QtGui import QImage
from queue import Queue
import cv2

from src.model.MatToQImageModel import matToQImageModel
from src.utils.Structures import *
from src.utils.Config import *


class ProcessingThreadModel(QThread):
    newFrame = pyqtSignal(QImage)
    updateStatisticsInGUI = pyqtSignal(ThreadStatisticsData)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

    def __init__(self, sharedImageBuffer, deviceUrl, cameraId, parent=None):
        super(QThread, self).__init__(parent)
        self.sharedImageBuffer = sharedImageBuffer
        self.cameraId = cameraId
        # Save Device Url
        self.deviceUrl = deviceUrl
        # Initialize members
        self.doStopMutex = QMutex()
        self.processingMutex = QMutex()
        self.t = QTime()
        self.processingTime = 0
        self.doStop = False
        self.enableFrameProcessing = False
        self.sampleNumber = 0
        self.fpsSum = 0.0
        self.fps = Queue()
        self.currentROI = QRect()
        self.imgProcFlags = ImageProcessingFlags()
        self.imgProcSettings = ImageProcessingSettings()
        self.statsData = ThreadStatisticsData()
        self.frame = None
        self.currentFrame = None

    def run(self):
        while True:
            ##############################
            # Stop thread if doStop=True #
            ##############################
            self.doStopMutex.lock()
            if self.doStop:
                self.doStop = False
                self.doStopMutex.unlock()
                break
            self.doStopMutex.unlock()
            ################################
            ################################

            # Save processing time
            self.processingTime = self.t.elapsed()
            # Start timer (used to calculate processing rate)
            self.t.start()

            with QMutexLocker(self.processingMutex):
                self.currentFrame = self.sharedImageBuffer.getByDeviceUrl(self.deviceUrl).get()[
                    self.currentROI.y():(self.currentROI.y() + self.currentROI.height()),
                    self.currentROI.x():(self.currentROI.x() + self.currentROI.width())].copy()

                ##################################
                # PERFORM IMAGE PROCESSING BELOW #
                ##################################

                # Grayscale conversion (in-place operation)
                if self.imgProcFlags.grayscaleOn and (
                        self.currentFrame.shape[2] == 3 or self.currentFrame.shape[2] == 4):
                    self.currentFrame = cv2.cvtColor(
                        self.currentFrame, cv2.COLOR_BGR2GRAY)

                # Smooth (in-place operations)
                if self.imgProcFlags.smoothOn:
                    if self.imgProcSettings.smoothType == 0:
                        # BLUR
                        self.currentFrame = cv2.blur(self.currentFrame,
                                                     (self.imgProcSettings.smoothParam1,
                                                      self.imgProcSettings.smoothParam2))
                    elif self.imgProcSettings.smoothType == 1:
                        # GAUSSIAN
                        self.currentFrame = cv2.GaussianBlur(self.currentFrame,
                                                             (self.imgProcSettings.smoothParam1,
                                                              self.imgProcSettings.smoothParam2),
                                                             sigmaX=self.imgProcSettings.smoothParam3,
                                                             sigmaY=self.imgProcSettings.smoothParam4)
                    elif self.imgProcSettings.smoothType == 2:
                        # MEDIAN
                        self.currentFrame = cv2.medianBlur(
                            self.currentFrame, self.imgProcSettings.smoothParam1)

                # Dilate
                if self.imgProcFlags.dilateOn:
                    self.currentFrame = cv2.dilate(self.currentFrame, self.kernel,
                                                   iterations=self.imgProcSettings.dilateNumberOfIterations)
                # Erode
                if self.imgProcFlags.erodeOn:
                    self.currentFrame = cv2.erode(self.currentFrame, self.kernel,
                                                  iterations=self.imgProcSettings.erodeUrlOfIterations)
                # Flip
                if self.imgProcFlags.flipOn:
                    self.currentFrame = cv2.flip(
                        self.currentFrame, self.imgProcSettings.flipCode)
                # Canny edge detection
                if self.imgProcFlags.cannyOn:
                    self.currentFrame = cv2.Canny(self.currentFrame,
                                                  threshold1=self.imgProcSettings.cannyThreshold1,
                                                  threshold2=self.imgProcSettings.cannyThreshold2,
                                                  apertureSize=self.imgProcSettings.cannyApertureSize,
                                                  L2gradient=self.imgProcSettings.cannyL2gradient)

                # Speed estimation
                if self.imgProcFlags.speedOn:
                    self.currentFrame = cv2.putText(
                        self.currentFrame, "Speed estimation",(94, 92),cv2.FONT_HERSHEY_SIMPLEX,1, (255, 0, 0),2)

                ##################################
                # PERFORM IMAGE PROCESSING ABOVE #
                ##################################

                # Convert Mat to QImage
                self.frame = matToQImage(self.currentFrame)

                # Inform GUI thread of new frame (QImage)
                self.newFrame.emit(self.frame)

        self.updateFPS(self.processingTime)
        self.statsData.nFramesProcessed += 1
        self.updateStatisticsInGUI.emit(self.statsData)

        qDebug("Stopping processing thread...")

    def doShowImage(self, val):
        with QMutexLocker(self.processingMutex):
            self.doShow = val

    def updateFPS(self, timeElapsed):
        # Add instantaneous FPS value to queue
        if timeElapsed > 0:
            self.fps.put(1000 / timeElapsed)
            # Increment sample number
            self.sampleNumber += 1

        # Maximum size of queue is DEFAULT_PROCESSING_FPS_STAT_QUEUE_LENGTH
        if self.fps.qsize() > PROCESSING_FPS_STAT_QUEUE_LENGTH:
            self.fps.get()

        # Update FPS value every DEFAULT_PROCESSING_FPS_STAT_QUEUE_LENGTH samples
        if self.fps.qsize() == PROCESSING_FPS_STAT_QUEUE_LENGTH and self.sampleNumber == PROCESSING_FPS_STAT_QUEUE_LENGTH:
            # Empty queue and store sum
            while not self.fps.empty():
                self.fpsSum += self.fps.get()
            # Calculate average FPS
            self.statsData.averageFPS = self.fpsSum / PROCESSING_FPS_STAT_QUEUE_LENGTH
            # Reset sum
            self.fpsSum = 0.0
            # Reset sample number
            self.sampleNumber = 0

    def stop(self):
        with QMutexLocker(self.doStopMutex):
            self.doStop = True

    def updateBoxesBufferMax(self, boxesBufferMax):
        with QMutexLocker(self.processingMutex):
            self.boxesBufferMax = boxesBufferMax

    def updateImageProcessingFlags(self, imgProcFlags):
        with QMutexLocker(self.processingMutex):
            self.imgProcFlags.grayscaleOn = imgProcFlags.grayscaleOn
            self.imgProcFlags.smoothOn = imgProcFlags.smoothOn
            self.imgProcFlags.dilateOn = imgProcFlags.dilateOn
            self.imgProcFlags.erodeOn = imgProcFlags.erodeOn
            self.imgProcFlags.flipOn = imgProcFlags.flipOn
            self.imgProcFlags.cannyOn = imgProcFlags.cannyOn
            self.imgProcFlags.speedOn = imgProcFlags.speedOn

    def updateImageProcessingSettings(self, imgProcSettings):
        with QMutexLocker(self.processingMutex):
            self.imgProcSettings.smoothType = imgProcSettings.smoothType
            self.imgProcSettings.smoothParam1 = imgProcSettings.smoothParam1
            self.imgProcSettings.smoothParam2 = imgProcSettings.smoothParam2
            self.imgProcSettings.smoothParam3 = imgProcSettings.smoothParam3
            self.imgProcSettings.smoothParam4 = imgProcSettings.smoothParam4
            self.imgProcSettings.dilateNumberOfIterations = imgProcSettings.dilateNumberOfIterations
            self.imgProcSettings.erodeUrlOfIterations = imgProcSettings.erodeUrlOfIterations
            self.imgProcSettings.flipCode = imgProcSettings.flipCode
            self.imgProcSettings.cannyThreshold1 = imgProcSettings.cannyThreshold1
            self.imgProcSettings.cannyThreshold2 = imgProcSettings.cannyThreshold2
            self.imgProcSettings.cannyApertureSize = imgProcSettings.cannyApertureSize
            self.imgProcSettings.cannyL2gradient = imgProcSettings.cannyL2gradient

    def setROI(self, roi):
        with QMutexLocker(self.processingMutex):
            self.currentROI.setX(roi.x())
            self.currentROI.setY(roi.y())
            self.currentROI.setWidth(roi.width())
            self.currentROI.setHeight(roi.height())

    def getCurrentROI(self):
        return QRect(self.currentROI.x(), self.currentROI.y(), self.currentROI.width(), self.currentROI.height())
