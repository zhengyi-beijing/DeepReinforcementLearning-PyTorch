import numpy as np
import math


class PathGuider:
    def __init__(self):

        self.k = 5
        self.dt = 0.01

        self.t = 0.0
        self.updateTrajPos()

    def updateTrajPos(self):
        self.z = self.k * self.t
        self.r = math.cos(self.t * 5) * 45
        self.x = self.r * math.cos(self.t * 7)
        self.y = self.r * math.sin(self.t * 7)
        self.trajPos = np.array([self.x, self.y, self.z])

    def getTrajPos(self):
        return self.trajPos.copy()

    def step(self, pos, thresh):

        dist = self.trajPos - pos
        distance = np.linalg.norm(dist)


        while distance < thresh:
            self.t += self.dt
            self.updateTrajPos()
            dist = self.trajPos - pos
            distance = np.linalg.norm(dist)



if __name__ == '__main__':

    guide = PathGuider()

    pos = np.array([0.0, 0.0, 0.0])

    record = [pos.copy()]

    target = guide.getTrajPos()

    direction = target - pos
    direction = direction / np.linalg.norm(direction)
    for i in range(10000):
        pos += direction
        record.append(pos.copy())
        guide.step(pos, 5)

        target = guide.getTrajPos()

        direction = target - pos
        direction = direction / np.linalg.norm(direction)


    record = np.array(record)
    np.savetxt('followedTraj.txt', record)