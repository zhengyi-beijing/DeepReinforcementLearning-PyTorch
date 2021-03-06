from Env.CustomEnv.ThreeDNavigation.ActiveParticle3DSimulatorPython import ActiveParticle3DSimulatorPython
from Env.CustomEnv.ThreeDNavigation.dynamicObstacleMover import Ellipsoid
from Env.CustomEnv.ThreeDNavigation.NavigationExamples.Obstacles.CurveVessels.curvedVessel import CurvedVessel

import numpy as np
import random
import json
import os
from sklearn.metrics.pairwise import euclidean_distances
import math
import sys
from scipy.spatial import distance


# notes for gravity
# gravity will have unit of kT/a, then every second, the displacement is given by G D/kT
# given G = 5kT/a, every second the displacement is 5 D/a and is 5 D/a^2 in radius,
# which is around 0.1 a per s(D = 2.145 e-14)
# if G = 50, then it is 1a per s

class RBCObstacle:

    def __init__(self, center, scale, orientVec):
        # here I use unit of 1um, a RBC has diameter of 8um, thickness at thickest point of 2.5um
        # a minimum thickness is 1um
        # based on these parameters we have the following
        self.center = center
        self.scale = scale

        self.centralHeight = 0.5 * scale

        self.radius = 4 * scale
        self.slope = 0.2
        self.orientVec = orientVec

    def isInside(self, pointVec):
        # first convert
        distanceVec = pointVec - self.center
        Heights = abs(np.dot(distanceVec, self.orientVec))
        distance2Axis = np.linalg.norm((distanceVec - np.outer(Heights, self.orientVec)), axis = 1)

        return np.logical_and(distance2Axis < (self.radius + 1.0),(Heights - self.centralHeight - distance2Axis * self.slope) < 1.0)


class ActiveParticle3DEnv():
    def __init__(self, configName, randomSeed = 1, obstacleConstructorCallBack = None, curvedVessel = None):

        with open(configName) as f:
            self.config = json.load(f)
        self.randomSeed = randomSeed
        self.obstacleConstructorCallBack = obstacleConstructorCallBack
        self.curvedVessel = curvedVessel
        self.model = ActiveParticle3DSimulatorPython(configName, randomSeed)
        self.read_config()
        self.initilize()

        #self.padding = self.config['']

    def initilize(self):
        if not os.path.exists('Traj'):
            os.makedirs('Traj')
        # import parameter for vector env
        self.viewer = None
        self.steps_beyond_done = None
        self.stepCount = 0

        self.info = {}

        random.seed(self.randomSeed)
        np.random.seed(self.randomSeed)

        self.initObsMat()
        self.constructSensorArrayIndex()
        self.epiCount = -1

    def read_config(self):

        self.receptHalfWidth = 5
        if 'receptHalfWidth' in self.config:
            self.receptHalfWidth = self.config['receptHalfWidth']
        self.padding = 10
        if 'obstacleMapPaddingWidth' in self.config:
            self.padding = self.config['obstacleMapPaddingWidth']

        self.sensorPixelSize = 2
        if 'sensorPixelSize' in self.config:
            self.sensorPixelSize = self.config['sensorPixelSize']

        self.receptWidth = 2 * self.receptHalfWidth + 1
        self.targetClipLength = (2 * self.receptHalfWidth + 1) * self.sensorPixelSize

        if 'targetClipLength' in self.config:
            self.targetClipLength = self.config['targetClipLength']

        self.stateDim = (self.receptWidth, self.receptWidth)



        self.sensorArrayWidth = (2*self.receptHalfWidth + 1)


        self.episodeEndStep = 500
        if 'episodeLength' in self.config:
            self.episodeEndStep = self.config['episodeLength']

        self.particleType = self.config['particleType']
        typeList = ['VANILLASP','SLIDER']
        if self.particleType not in typeList:
            sys.exit('particle type not right!')

        if self.particleType == 'SLIDER':
            self.nbActions = 2
        elif self.particleType == 'VANILLASP':
            self.nbActions = 1


        self.startThresh = 1
        self.endThresh = 1
        self.distanceThreshDecay = 10000

        self.targetThreshFlag = False

        if 'targetThreshFlag' in self.config:
            self.targetThreshFlag = self.config['targetThreshFlag']

        if 'target_start_thresh' in self.config:
            self.startThresh = self.config['target_start_thresh']
        if 'target_end_thresh' in self.config:
            self.endThresh = self.config['target_end_thresh']
        if 'distance_thresh_decay' in self.config:
            self.distanceThreshDecay = self.config['distance_thresh_decay']

        self.obstacleFlag = False
        if 'obstacleFlag' in self.config:
            self.obstacleFlag = self.config['obstacleFlag']

        self.multiMapFlag = False

        if self.obstacleFlag:

            self.wallRadius = self.config['wallRadius']
            self.wallHeight = self.config['wallHeight']

            if 'multiMapFlag' in self.config:
                self.multiMapFlag = self.config['multiMapFlag']
                if self.multiMapFlag:
                    self.multiMapProbs = self.config['multiMapProbs']
                    self.multiMapNames = self.config['multiMapNames']
                    self.numMaps = len(self.multiMapNames)
            self.constructObstacles()

        self.nStep = self.config['modelNStep']

        self.distanceScale = 20
        if 'distanceScale' in self.config:
            self.distanceScale = self.config['distanceScale']

        self.actionPenalty = 0.0
        if 'actionPenalty' in self.config:
            self.actionPenalty = self.config['actionPenalty']

        self.obstaclePenalty = 0.0
        if 'obstaclePenalty' in self.config:
            self.obstaclePenalty = self.config['obstaclePenalty']

        self.finishThresh = 5.0
        if 'finishThresh' in self.config:
            self.finishThresh = self.config['finishThresh']

        self.timingFlag = False
        if 'timingFlag' in self.config:
            self.timingFlag = self.config['timingFlag']

            self.timeScale = 100
            if 'timeScale' in self.config:
                self.timeScale = self.config['timeScale']

            self.timeWindowLocation = self.config['timeWindowLocation']
            self.rewardArray = self.config['rewardArray']
            self.randomEpisode = self.config['randomEpisode']

        self.localFrameFlag = False
        if 'localFrameFlag' in self.config:
            self.localFrameFlag = self.config['localFrameFlag']

        # orient control will provide orientation vector to be aligned
        self.orientControlFlag = False
        if 'orientControlFlag' in self.config:
            self.orientControlFlag = self.config['orientControlFlag']
            if self.orientControlFlag:
                if self.particleType == 'VANILLASP':
                    raise Exception("particle type vanilla does not support orientControl")
                self.nbActions = 3

        self.vesselCapFlag = True
        if 'vesselCapFlag' in self.config:
            self.vesselCapFlag = self.config['vesselCapFlag']


        self.RBCInitialMoveFlag = False
        if 'RBCInitialMoveFlag' in self.config:
            self.RBCInitialMoveFlag = self.config['RBCInitialMoveFlag']
            self.RBCInitialMoveSteps = self.config['RBCInitialMoveSteps']
            self.RBCInitialMoveFreq = self.config['RBCInitialMoveFreq']



    def thresh_by_episode(self, step):
        return self.endThresh + (
                self.startThresh - self.endThresh) * math.exp(-1. * step / self.distanceThreshDecay)

    def constructObstacles(self):

        if not self.multiMapFlag:

            mapName = None
            if 'mapName' in self.config:
                mapName = self.config['mapName']
                self.obstacles, self.obstacleCenters = self.obstacleConstructorCallBack(mapName)
            else:
                self.obstacles, self.obstacleCenters = self.obstacleConstructorCallBack()
        else:

            self.obstaclesList = []
            self.obstaclesCentersList = []
            self.wallHeights = []
            self.wallRadii = []
            for mapName in self.multiMapNames:
                obstacles, obstacleCenters = self.obstacleConstructorCallBack(mapName)
                self.obstaclesCentersList.append(obstacleCenters)
                self.obstaclesList.append(obstacles)

                with open(mapName, 'r') as f:
                    config = json.load(f)
                wallHeight, wallRadius = config['heightRadius']
                self.wallHeights.append(wallHeight)
                self.wallRadii.append(wallRadius)
            self.obstacles, self.obstacleCenters = self.obstaclesList[0], self.obstaclesCentersList[0]
            self.wallHeight, self.wallRadius = self.wallHeights[0], self.wallRadii[0]

    def constructSensorArrayIndex(self):
        x_int = np.arange(-self.receptHalfWidth, self.receptHalfWidth + 1)
        y_int = np.arange(-self.receptHalfWidth, self.receptHalfWidth + 1)
        z_int = np.arange(-self.receptHalfWidth, self.receptHalfWidth + 1)
        [Y, X, Z] = np.meshgrid(y_int, x_int, z_int)
        self.sensorIndex = np.stack((X.reshape(-1), Y.reshape(-1), Z.reshape(-1)), axis=1)
        self.sensorPos = self.sensorIndex * self.sensorPixelSize
    def getSensorInfo(self):
    # sensor information needs to consider orientation information
    # add integer resentation of location
    #    index = self.senorIndex + self.currentState + np.array([self.padding, self.padding])
        self.localFrame = self.model.getLocalFrame()
    # in local Frame, each row is the vector of the local frame
    # transform from local coordinate to global coordinate is then given by localFrame * localCood or localCood * localFrame
        self.localFrame.shape = (3, 3)
    # this is rotation matrix transform from local coordinate system to lab coordinate system
        rotMatrx = self.localFrame
        if self.localFrameFlag:
            sensorGlobalPos = np.matmul(self.sensorPos, rotMatrx.T)
        else:
            sensorGlobalPos = self.sensorPos.copy().astype(np.float32)

        sensorGlobalPos[:, 0] += self.currentState[0]
        sensorGlobalPos[:, 1] += self.currentState[1]
        sensorGlobalPos[:, 2] += self.currentState[2]

        pDist = euclidean_distances([self.currentState[0:3]], self.obstacleCenters)

        overlapVec = np.zeros(len(self.sensorIndex), dtype=np.uint8)
        for idx, dist in enumerate(pDist[0]):
            if dist < self.targetClipLength:
                overlapVec += self.obstacles[idx].isInside(sensorGlobalPos)

        overlapVec += self.outsideWall(sensorGlobalPos)

    # use augumented obstacle matrix to check collision
        self.sensorInfoMat = np.reshape(overlapVec, (self.receptWidth, self.receptWidth, self.receptWidth))

    def getHindSightExperience(self, state, action, nextState, info):

        if self.hindSightInfo['obstacle']:
            return None, None, None, None
        else:
            targetNew = self.hindSightInfo['currentState'][0: 3]
            distance = targetNew - self.hindSightInfo['previousState'][0:3]

            distanceLength = np.linalg.norm(distance, ord=2)
            distance = distance / distanceLength * min(self.targetClipLength, distanceLength)
            if self.obstacleFlag:
                if self.localFrameFlag:
                    orientVec = self.hindSightInfo['previousState'][3:]
                    localTarget = self.getLocalTarget(distance, orientVec)
                    targetStateNew = localTarget / self.distanceScale
                    targetStateNew = np.concatenate((self.hindSightInfo['previousState'][3:], localTarget / self.distanceScale))

                else:
                    targetStateNew = np.concatenate((self.hindSightInfo['previousState'][3:], distance / self.distanceScale))
                stateNew = {'sensor': state['sensor'],
                         'target': targetStateNew}
            else:
                if not self.timingFlag:
                    if self.localFrameFlag:
                        orientVec = self.hindSightInfo['previousState'][3:]
                        localTarget = self.getLocalTarget(distance, orientVec)
                        stateNew = localTarget / self.distanceScale
                        stateNew = np.concatenate(
                            (self.hindSightInfo['previousState'][3:], localTarget / self.distanceScale))
                    else:
                        stateNew = np.concatenate((self.hindSightInfo['previousState'][3:], distance / self.distanceScale))
                else:
                    stateNew = np.concatenate((self.hindSightInfo['previousState'][3:], distance / self.distanceScale, [state[-1]]))

            rewardNew = 1.0
            if self.timingFlag:
                if info['timeStep'] < self.timeWindowLocation[0]:
                    rewardNew = -1.0

            actionNew = action
            return stateNew, actionNew, None, rewardNew



    def actionPenaltyCal(self, action):
        raise NotImplementedError
        actionNorm = np.linalg.norm(action, ord=2)
        return -self.actionPenalty * actionNorm ** 2

    def outsideWall(self, points):
        # use xy to calculate axis
        distance2Axis = np.linalg.norm(points[:,0:2], axis=1)

        if self.curvedVessel is None:
            if self.vesselCapFlag:
                return np.logical_or(distance2Axis > self.wallRadius, np.logical_or(points[:,2] < 0.0, points[:,2] > self.wallHeight))
            else:
                return distance2Axis > self.wallRadius
        else:
            return self.curvedVessel.isOutsideVec(points)

    def inObstacle(self, point):
        if self.obstacleFlag:

            pDist = euclidean_distances([point], self.obstacleCenters)

            for idx, dist in enumerate(pDist[0]):
                if dist < self.targetClipLength:
                    inObstacle = self.obstacles[idx].isInside([point])

                    if inObstacle[0]:
                        return True

            # check if outside the wall
            if self.curvedVessel is not None:
                return self.curvedVessel.isOutside(point)
            else:
                r = math.sqrt((point[0])**2 + (point[1])**2)
                if r > (self.wallRadius - 1.0):
                    return True

                if point[2] > self.wallHeight or point[2] < 0.0:
                    return True

        return False

    def getLocalTarget(self, target, orientVec = None):
        if orientVec is None:
            self.localFrame = self.model.getLocalFrame()
            self.localFrame.shape = (3, 3)
            localTarget = np.dot(self.localFrame, target.T)
        else:
            phi = math.atan2(orientVec[1], orientVec[0])
            orientVec2 = np.array([-math.sin(phi), math.cos(phi), 0])
            orientVec3 = np.cross(orientVec, orientVec2)
            localFrame = np.array([orientVec, orientVec2, orientVec3])
            localTarget = np.dot(localFrame, target.T)
        return localTarget

    def step(self, action):
        self.hindSightInfo['obstacle'] = False
        self.hindSightInfo['previousState'] = self.currentState.copy()
        reward = 0.0
        #if self.customExploreFlag and self.epiCount < self.customExploreEpisode:
        #    action = self.getCustomAction()
        if not self.orientControlFlag:
            self.model.step(self.nStep, action)
        else:
            self.model.stepGivenDirector(self.nStep, action, self.localFrameFlag)
        self.currentState = self.model.getPositions()

        #self.currentState = self.currentState + 2.0 * np.array([action[0], action[1], 0])

        hitObs = self.inObstacle(self.currentState[0:3])
        if hitObs:
            # if hit obstacle, we move angle but not the position,
            #self.info['trapConfig'].append(self.currentState.copy())
            self.currentState[0:3] = self.hindSightInfo['previousState'][0:3]
            self.model.setInitialState(self.currentState[0], self.currentState[1], self.currentState[2],
                                          self.currentState[3], self.currentState[4], self.currentState[5])

            self.hindSightInfo['obstacle'] = True
            self.info['trapCount'] += 1
            reward -= self.obstaclePenalty

        self.hindSightInfo['currentState'] = self.currentState.copy()
        self.info['currentState'] = self.currentState.copy()
        self.info['targetState'] = self.targetState.copy()
        distance = self.targetState - self.currentState[0:3]

        # update step count
        self.stepCount += 1

        done = False

        if self.is_terminal(distance):
            reward = 1.0
            done = True



            if self.timingFlag:
                if self.stepCount < self.timeWindowLocation[0]:
                    reward = -1.0
                if self.stepCount > self.timeWindowLocation[0]:
                    reward = 1.0



        # distance will be changed from lab coordinate to local coordinate
        distanceLength = np.linalg.norm(distance, ord=2)
        distance = distance / distanceLength * min( self.targetClipLength, distanceLength)

        self.info['previousTarget'] = self.info['currentTarget'].copy()
        self.info['currentTarget'] = distance + self.currentState[:3]
        self.info['distance'] = np.linalg.norm(distance)
        self.info['timeStep'] = self.stepCount
        if self.obstacleFlag:

            self.getSensorInfo()
            self.info['localFrame'] = self.localFrame
            if self.localFrameFlag:
                localTarget = self.getLocalTarget(distance)

                targetState = localTarget / self.distanceScale
                targetState = np.concatenate((self.currentState[3:], localTarget / self.distanceScale))

            else:
                targetState = np.concatenate((self.currentState[3:], distance / self.distanceScale))

            state = {'sensor': np.expand_dims(self.sensorInfoMat, axis=0),
                     'target': targetState}
        else:
            if not self.timingFlag:
                if self.localFrameFlag:
                    localTarget = self.getLocalTarget(distance)
                    self.info['localFrame'] = self.localFrame
                    state = np.concatenate((self.currentState[3:], localTarget / self.distanceScale))
                else:
                    state = np.concatenate((self.currentState[3:], distance / self.distanceScale))
            else:
                state = np.concatenate((self.currentState[3:], distance / self.distanceScale, [float(self.stepCount) / self.timeScale]))
        return state, reward, done, self.info.copy()

    def is_terminal(self, distance):
        return np.linalg.norm(distance, ord=np.inf) < self.finishThresh

    def generateTimeStep(self):
        if self.epiCount < self.randomEpisode:
            return random.choice(list(range(self.timeWindowLocation[0], self.timeWindowLocation[1])))
        elif self.epiCount < 2 * self.randomEpisode:
            return random.choice(list(range(self.timeWindowLocation[1])))

        else:
            return 0

    def reset_helper(self):
        targetThresh = float('inf')
        if self.targetThreshFlag:
            targetThresh = self.thresh_by_episode(self.epiCount) * 100
            if self.obstacleFlag:
                targetThresh = self.thresh_by_episode(self.epiCount) * max(self.wallHeight, self.wallRadius * 2)

            print('target thresh', targetThresh)
        self.currentState = np.array(self.config['currentState'], dtype=np.float)
        self.targetState = np.array(self.config['targetState'], dtype=np.float)


        if not self.obstacleFlag:
            if self.config['dynamicTargetFlag']:
                x = random.randint(0, 50)
                y = random.randint(0, 50)
                z = random.randint(0, 50)
                self.targetState = np.array([x, y, z], dtype=np.float)

            if self.config['dynamicInitialStateFlag']:
                while True:
                    x = random.randint(0, 50)
                    y = random.randint(0, 50)
                    z = random.randint(0, 50)

                    distanctVec = np.array([x, y, z],
                                           dtype=np.float32) - self.targetState
                    distance = np.linalg.norm(distanctVec, ord=np.inf)
                    if distance < targetThresh and not self.is_terminal(distanctVec):
                        break
                # set initial state
                print('target distance', distance)
                orientation = np.random.randn(3)
                self.currentState = np.concatenate((np.array([x, y, z], dtype=np.float32), orientation))


        if self.obstacleFlag:
            if self.config['dynamicTargetFlag']:
                while True:
                    r = random.randint(0, self.wallRadius - 1)
                    angle = random.random() * np.pi * 2
                    x = r * math.cos(angle)
                    y = r * math.sin(angle)
                    z = random.randint(0, self.wallHeight)
                    if not self.inObstacle(np.array([x, y, z])):
                        break

                self.targetState = np.array([x, y, z], dtype=np.float)

            if self.config['dynamicInitialStateFlag']:
                while True:
                    r = random.randint(0, self.wallRadius - 1)
                    angle = random.random() * np.pi * 2
                    x = r * math.cos(angle)
                    y = r * math.sin(angle)
                    z = random.randint(0, self.wallHeight)

                    distanctVec = np.array([x, y, z],
                                           dtype=np.float32) - self.targetState
                    distance = np.linalg.norm(distanctVec, ord=np.inf)
                    if distance < targetThresh and \
                            not self.inObstacle(np.array([x, y, z], dtype=np.float32)) \
                            and not self.is_terminal(distanctVec):
                        break
                # set initial state
                print('target distance', distance)
                orientation = np.random.randn(3)
                self.currentState = np.concatenate((np.array([x, y, z], dtype=np.float32), orientation))


    def resetMap(self):

        index = np.random.choice(self.numMaps, 1, p=self.multiMapProbs)[0]
        self.obstacles, self.obstacleCenters = self.obstaclesList[index], self.obstaclesCentersList[index]
        self.wallHeight, self.wallRadius = self.wallHeights[index], self.wallRadii[index]

        if self.multiMapNames[index] in self.config:
            self.curvedVessel = CurvedVessel(**self.config[self.multiMapNames[index]])
            print('construct curved vessels', self.multiMapNames[index])
        else:
            self.curvedVessel = None

        print('reset map', self.multiMapNames[index], self.wallHeight, self.wallRadius)

        if self.RBCInitialMoveFlag and self.epiCount % self.RBCInitialMoveFreq == 0:
            self.RBCConstructAndMove(self.RBCInitialMoveSteps)


    def reset(self):
        self.stepCount = 0
        self.epiCount += 1
        if self.timingFlag:
            self.stepCount = self.generateTimeStep()

        if self.multiMapFlag:
            self.resetMap()


        self.hindSightInfo = {}

        self.info = {}
        self.info['scaleFactor'] = self.distanceScale
        self.info['timeStep'] = self.stepCount
        self.info['trapCount'] = 0
        self.info['trapConfig'] = []



        self.reset_helper()
        self.model.createInitialState(self.currentState[0], self.currentState[1], self.currentState[2],
                                   self.currentState[3], self.currentState[4], self.currentState[5])



        # distance will be changed from lab coordinate to local coordinate
        distance = self.targetState - self.currentState[0:3]

        distanceLength = np.linalg.norm(distance, ord=2)
        distance = distance / distanceLength * min( self.targetClipLength, distanceLength)

        self.info['currentTarget'] = distance + self.currentState[:3]
        self.info['distance'] = np.linalg.norm(distance)

        if self.obstacleFlag:
            self.getSensorInfo()
            self.info['localFrame'] = self.localFrame
            if self.localFrameFlag:
                localTarget = self.getLocalTarget(distance)

                targetState = localTarget / self.distanceScale
                targetState = np.concatenate((self.currentState[3:], localTarget / self.distanceScale))

            else:
                targetState = np.concatenate((self.currentState[3:], distance / self.distanceScale))


            state = {'sensor': np.expand_dims(self.sensorInfoMat, axis=0),
                     'target': targetState}
        else:
            if not self.timingFlag:
                if self.localFrameFlag:
                    localTarget = self.getLocalTarget(distance)
                    self.info['localFrame'] = self.localFrame
                    state = localTarget / self.distanceScale
                    state = np.concatenate((self.currentState[3:], localTarget / self.distanceScale))
                else:
                    state = np.concatenate((self.currentState[3:], distance / self.distanceScale))
            else:
                state = np.concatenate((self.currentState[3:], distance / self.distanceScale, [float(self.stepCount) / self.timeScale]))
        return state

    def checkRBCOverlap(self, index):

        dist = euclidean_distances([self.RBCCenters[index]], self.RBCCenters)
        dist[dist == 0] = 100
        thresh = 2.0
        for i in range(dist.shape[1]):
            if dist[0, i] < 20: # typical RBC diameter
                dist = euclidean_distances(self.ellipsoids[index].keyPoints, self.ellipsoids[i].keyPoints)
                dist[dist == 0] = 100
                if np.any(dist < thresh):
                    return True
        return False


    def RBCMove(self, index, translationStepSize=1, rotationStepSize=0.5):

        self.ellipsoids[index].move(translationStepSize, rotationStepSize)
        if np.any(self.outsideWall(self.ellipsoids[index].keyPoints)):
            self.ellipsoids[index].moveBack()
            return
        self.RBCCenters[index] = self.ellipsoids[index].center
        if self.checkRBCOverlap(index):
            self.ellipsoids[index].moveBack()
            self.RBCCenters[index] = self.ellipsoids[index].center

    def RBCConstructAndMove(self, steps):

        self.ellipsoids = []
        self.RBCCenters = []
        for obs in self.obstacles:
            self.ellipsoids.append(Ellipsoid(obs.center, obs.scale, obs.orientVec))
            self.RBCCenters.append(obs.center)

        print('obs simulate')
        for i in range(steps):
            for j in range(len(self.ellipsoids)):
                self.RBCMove(j)

        # set the obstacle centers
        for i in range(len(self.ellipsoids)):
            self.obstacles[i].center = self.ellipsoids[i].center
            self.obstacles[i].orientVec = self.ellipsoids[i].orient
            self.obstacleCenters[i] = self.ellipsoids[i].center



    def initObsMat(self):
        return
        # fileName = self.config['mapName']
        # self.mapMat = np.genfromtxt(fileName + '.txt')
        # self.mapShape = self.mapMat.shape
        # padW = self.config['obstacleMapPaddingWidth']
        # obsMapSizeOne = self.mapMat.shape[0] + 2*padW
        # obsMapSizeTwo = self.mapMat.shape[1] + 2*padW
        # self.obsMap = np.ones((obsMapSizeOne, obsMapSizeTwo))
        # self.obsMap[padW:-padW, padW:-padW] = self.mapMat
        #
        # self.obsMap -= 0.5
        # self.mapMat -= 0.5
        # np.savetxt(self.config['mapName']+'obsMap.txt', self.obsMap, fmt='%.1f', delimiter='\t')